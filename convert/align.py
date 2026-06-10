"""Steps 1.5–1.7 — rest-pose alignment fixes (no reference PMX, only bundled JSON).

  fix_forearm_bend          straighten the forearm collinear with the upper arm
  align_arms_to_canonical   align upper-arm / forearm direction to MMD A-pose canonical
  align_fingers_to_canonical align finger root direction to canonical

Each computes pose-space rotations and bakes them into a new rest pose (the mesh
follows via a duplicated armature modifier). Ported from the XPS-fixes module.
"""

import bpy
import json
import math
import os
from mathutils import Matrix, Vector

from ..bone_utils import apply_armature_transforms


_CANON_ARM_CACHE = None
_CANON_FINGER_CACHE = None


def _presets_path(name):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "presets", name)


def _load_canonical_arm_dirs():
    global _CANON_ARM_CACHE
    if _CANON_ARM_CACHE is not None:
        return _CANON_ARM_CACHE
    try:
        with open(_presets_path("canonical_arm_dirs.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for side in ("L", "R"):
            arm = data["arms"][side]
            result[side] = (Vector(arm["upper_dir"]).normalized(), Vector(arm["fore_dir"]).normalized())
        _CANON_ARM_CACHE = result
        return result
    except Exception as e:
        print(f"[align canonical-arm] 读取失败: {e}")
        return None


def _load_canonical_finger_dirs():
    global _CANON_FINGER_CACHE
    if _CANON_FINGER_CACHE is not None:
        return _CANON_FINGER_CACHE
    try:
        with open(_presets_path("canonical_finger_dirs.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {side: {name: Vector(v).normalized() for name, v in data["fingers"][side].items()}
                  for side in ("L", "R")}
        _CANON_FINGER_CACHE = result
        return result
    except Exception as e:
        print(f"[align canonical-finger] 读取失败: {e}")
        return None


def _find_arm_chain(obj, side):
    """Return (upper_arm, elbow, wrist) names across rig conventions, or None."""
    xps_side = "left" if side == "L" else "right"
    lr = "l" if side == "L" else "r"
    jp = "左" if side == "L" else "右"
    candidates = [
        (f"{jp}腕", f"{jp}ひじ", f"{jp}手首"),
        (f"arm {xps_side} shoulder 2", f"arm {xps_side} elbow", f"arm {xps_side} wrist"),
        (f"{lr}ShldrBend", f"{lr}ForearmBend", f"{lr}Hand"),
        (f"mixamorig:{xps_side.capitalize()}Arm", f"mixamorig:{xps_side.capitalize()}ForeArm", f"mixamorig:{xps_side.capitalize()}Hand"),
        (f"Upper Arm.{side}", f"Lower Arm.{side}", f"Hand.{side}"),
        (f"UpperArm_{side}", f"LowerArm_{side}", f"Hand_{side}"),
        (f"腕.{side}", f"ひじ.{side}", f"手首.{side}"),
    ]
    bones = obj.data.bones
    for u, e, w in candidates:
        if u in bones and e in bones and w in bones:
            return u, e, w
    return None


def _bake_pose_delta_to_rest(context, obj, plans, log_tag):
    """Apply (bone, pivot_world, axis_world, angle) rotations in pose mode, bake as rest."""
    if not plans:
        return 'FINISHED'

    meshes_with_arm = []
    for m in bpy.data.objects:
        if m.type != 'MESH' or m.data.shape_keys:
            continue
        if any(mod.type == 'ARMATURE' and mod.object == obj for mod in m.modifiers):
            meshes_with_arm.append(m)

    created_temp = False
    if not meshes_with_arm:
        try:
            bpy.ops.mesh.primitive_cube_add(size=0.5)
            tmp = context.active_object
            tmp.name = "XPS_FIXES_TEMP_MESH"
            mod = tmp.modifiers.new(name="Armature", type='ARMATURE')
            mod.object = obj
            tmp["is_temp_mesh"] = True
            meshes_with_arm.append(tmp)
            created_temp = True
        except Exception as e:
            print(f"[{log_tag}] 创建临时网格失败: {e}")
            return 'CANCELLED'

    for m in meshes_with_arm:
        for mod in list(m.modifiers):
            if mod.type == 'ARMATURE' and mod.object == obj and "_copy" not in mod.name:
                new_mod = m.modifiers.new(name=mod.name + "_copy", type='ARMATURE')
                new_mod.object = mod.object
                new_mod.use_vertex_groups = mod.use_vertex_groups
                new_mod.use_bone_envelopes = mod.use_bone_envelopes
                break

    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.rot_clear()
    bpy.ops.pose.scale_clear()
    bpy.ops.pose.loc_clear()
    bpy.ops.pose.select_all(action='DESELECT')

    for bone_name, pivot, axis, angle in plans:
        pb = obj.pose.bones[bone_name]
        rot_w = Matrix.Rotation(angle, 4, axis)
        delta = Matrix.Translation(pivot) @ rot_w @ Matrix.Translation(-pivot)
        pb.matrix = delta @ pb.matrix
        context.view_layer.update()

    try:
        for m in meshes_with_arm:
            context.view_layer.objects.active = m
            for mod in list(m.modifiers):
                if mod.type == 'ARMATURE' and mod.object == obj and "_copy" in mod.name:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    break
    except RuntimeError as e:
        for m in meshes_with_arm:
            for mod in list(m.modifiers):
                if "_copy" in mod.name:
                    m.modifiers.remove(mod)
        print(f"[{log_tag}] 应用 modifier 失败: {e}")
        return 'CANCELLED'

    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.armature_apply()
    bpy.ops.object.mode_set(mode='OBJECT')

    if created_temp:
        for m in meshes_with_arm:
            if m.get("is_temp_mesh"):
                bpy.data.objects.remove(m, do_unlink=True)
    return 'FINISHED'


_FINGER_CHAINS = [
    ("親指０", "親指１", "親指２"), ("人指１", "人指２", "人指３"),
    ("中指１", "中指２", "中指３"), ("薬指１", "薬指２", "薬指３"),
    ("小指１", "小指２", "小指３"),
]


class OBJECT_OT_fix_forearm_bend(bpy.types.Operator):
    """L1 修正：把小手臂拉直到与上臂共线，然后烘焙到 rest pose。"""
    bl_idname = "object.fix_forearm_bend"
    bl_label = "L1: 修正前腕弯曲"
    bl_description = "把小手臂拉直到与上臂共线，烘焙为新 rest pose"
    ANGLE_THRESHOLD_DEG = 2.0

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        plans = []
        for side in ("L", "R"):
            chain = _find_arm_chain(obj, side)
            if not chain:
                continue
            u_name, e_name, w_name = chain
            u_head = obj.matrix_world @ obj.pose.bones[u_name].head
            e_head = obj.matrix_world @ obj.pose.bones[e_name].head
            w_head = obj.matrix_world @ obj.pose.bones[w_name].head
            upper_dir = (e_head - u_head).normalized()
            fore_dir = (w_head - e_head).normalized()
            if upper_dir.length == 0 or fore_dir.length == 0:
                continue
            angle = upper_dir.angle(fore_dir)
            if angle < math.radians(self.ANGLE_THRESHOLD_DEG):
                print(f"[align fix-forearm] {side}: 已共线 ({math.degrees(angle):.2f}°)，跳过")
                continue
            axis = fore_dir.cross(upper_dir)
            if axis.length < 1e-6:
                continue
            axis.normalize()
            plans.append((e_name, e_head.copy(), axis, angle))
            print(f"[align fix-forearm] {side}: {e_name} 旋转 {math.degrees(angle):.2f}° 拉直")

        if not plans:
            self.report({'INFO'}, "前腕已接近直线，无需修正")
            return {'FINISHED'}
        if _bake_pose_delta_to_rest(context, obj, plans, "align fix-forearm") != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"前腕弯曲修正完成 ({len(plans)} 处)")
        return {'FINISHED'}


class OBJECT_OT_align_arms_to_canonical(bpy.types.Operator):
    """L1 修正：把上臂 / 前腕方向对齐到标准 MMD A-pose canonical，烘焙到 rest pose。"""
    bl_idname = "object.align_arms_to_canonical"
    bl_label = "L1: 对齐上臂到 canonical"
    bl_description = "把上臂/前腕方向对齐到内置 MMD A-pose canonical，烘焙为新 rest pose"
    ANGLE_THRESHOLD_DEG = 0.5

    def _build_plan(self, obj, side, ref_upper_dir, ref_fore_dir):
        plans = []
        chain = _find_arm_chain(obj, side)
        if not chain:
            return plans
        u, e, w = chain
        conv_u = obj.data.bones[u].head_local.copy()
        conv_e = obj.data.bones[e].head_local.copy()
        conv_w = obj.data.bones[w].head_local.copy()

        dir_conv_upper = (conv_e - conv_u).normalized()
        upper_angle = dir_conv_upper.angle(ref_upper_dir)
        upper_axis = None
        upper_angle_valid = upper_angle >= math.radians(self.ANGLE_THRESHOLD_DEG)
        if upper_angle_valid:
            upper_axis = dir_conv_upper.cross(ref_upper_dir)
            if upper_axis.length < 1e-6:
                upper_angle_valid = False
            else:
                upper_axis.normalize()
                plans.append((u, conv_u.copy(), upper_axis, upper_angle))
                print(f"[align align-arms] {side}: upper {u} 旋转 {math.degrees(upper_angle):.2f}°")

        if upper_angle_valid:
            R = Matrix.Rotation(upper_angle, 3, upper_axis)
            conv_e_new = conv_u + R @ (conv_e - conv_u)
            conv_w_new = conv_u + R @ (conv_w - conv_u)
        else:
            conv_e_new = conv_e
            conv_w_new = conv_w

        dir_conv_fore = (conv_w_new - conv_e_new).normalized()
        fore_angle = dir_conv_fore.angle(ref_fore_dir)
        if fore_angle >= math.radians(self.ANGLE_THRESHOLD_DEG):
            fore_axis = dir_conv_fore.cross(ref_fore_dir)
            if fore_axis.length > 1e-6:
                fore_axis.normalize()
                plans.append((e, conv_e_new.copy(), fore_axis, fore_angle))
                print(f"[align align-arms] {side}: forearm {e} 旋转 {math.degrees(fore_angle):.2f}°")
        return plans

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        canon = _load_canonical_arm_dirs()
        if not canon:
            self.report({'ERROR'}, "canonical_arm_dirs.json 读取失败")
            return {'CANCELLED'}

        all_plans = []
        for side in ("L", "R"):
            if side in canon:
                ref_upper, ref_fore = canon[side]
                all_plans.extend(self._build_plan(obj, side, ref_upper, ref_fore))

        if not all_plans:
            self.report({'INFO'}, f"已接近 canonical (<{self.ANGLE_THRESHOLD_DEG}°)，无需修正")
            return {'FINISHED'}
        if _bake_pose_delta_to_rest(context, obj, all_plans, "align align-arms") != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"上臂对齐完成 ({len(all_plans)} 处)")
        return {'FINISHED'}


class OBJECT_OT_align_fingers_to_canonical(bpy.types.Operator):
    """L1 修正：把手指根段方向 (根骨 → 第1节) 对齐到 canonical (左/右 命名)。"""
    bl_idname = "object.align_fingers_to_canonical"
    bl_label = "L1: 对齐手指到 canonical"
    bl_description = "把手指根段方向对齐到内置 canonical，烘焙为新 rest pose"
    ANGLE_THRESHOLD_DEG = 1.0

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        canon = _load_canonical_finger_dirs()
        if not canon:
            self.report({'ERROR'}, "canonical_finger_dirs.json 读取失败")
            return {'CANCELLED'}

        plans = []
        for side in ("L", "R"):
            jp = "左" if side == "L" else "右"
            for chain in _FINGER_CHAINS:
                conv_root = obj.data.bones.get(f"{jp}{chain[0]}")
                conv_tip = obj.data.bones.get(f"{jp}{chain[1]}")
                if not conv_root or not conv_tip:
                    continue
                conv_dir = (conv_tip.head_local - conv_root.head_local)
                if conv_dir.length < 1e-6:
                    continue
                conv_dir = conv_dir.normalized()
                ref_dir = canon.get(side, {}).get(chain[0])
                if ref_dir is None:
                    continue
                angle = conv_dir.angle(ref_dir)
                if angle < math.radians(self.ANGLE_THRESHOLD_DEG):
                    continue
                axis = conv_dir.cross(ref_dir)
                if axis.length < 1e-6:
                    continue
                axis.normalize()
                plans.append((f"{jp}{chain[0]}", conv_root.head_local.copy(), axis, angle))
                print(f"[align align-fingers] {side}: {jp}{chain[0]} 旋转 {math.degrees(angle):.2f}°")

        if not plans:
            self.report({'INFO'}, "手指方向已接近 canonical，无需修正")
            return {'FINISHED'}
        if _bake_pose_delta_to_rest(context, obj, plans, "align align-fingers") != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"手指对齐完成 ({len(plans)} 处)")
        return {'FINISHED'}
