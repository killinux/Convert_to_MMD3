"""Semi-standard bones: twist (腕捩/手捩), leg-D (足D/ひざD/足首D), shoulder-P (肩P/肩C).

These three used to live in three files with two different relay mechanisms — twist
deferred to mmd_tools, while leg-D and 肩P hand-built _dummy_/_shadow_ bones and wired
TRANSFORM + COPY_TRANSFORMS constraints by hand (~300 lines, duplicating exactly what
mmd_tools.apply_additional_transform produces).

Here every operator is a *pure geometry builder*: it creates the bones, reparents the
deform children, splits/renames weights, and (twist only) fixes the twist axis. It does
NOT build any relay. The 付与 grants are declared once in grants.py and realised by a
single apply_additional_transform — mmd_tools then chooses a direct constraint (aligned:
leg-D / 肩C) or a _dummy_/_shadow_ relay (misaligned-for-display: the up-pointing twist
subs) on its own.

`finalize` (default True) makes a button self-contained (set grants + apply); the
pipeline passes finalize=False and runs one finalize after all three are built.
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Vector

from . import grants
from .weights.twist import split_twist_weights


def _finalize(obj):
    """Set all 付与 grants then let mmd_tools build every relay (direct or dummy/shadow)."""
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    grants.apply_grants(obj)
    try:
        bpy.ops.mmd_tools.apply_additional_transform()
    except Exception as e:
        print(f"[semistandard] apply_additional_transform: {e}")


def _regroup(obj):
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.create_bone_group()
    except Exception as e:
        print(f"[semistandard] create_bone_group: {e}")


# ============================================================
# Twist bones
# ============================================================

class OBJECT_OT_add_twist_bone(bpy.types.Operator):
    """对腕部和手部骨骼进行捩骨设置（几何 + 权重 + 轴固定；中转链由 mmd_tools 统一建）。

    主捩骨沿臂、带 fixed_axis、VMD 直接驱动；子捩骨竖直朝上(与主捩骨不对齐)，使 mmd_tools
    的 apply_additional_transform 自动建 _dummy_/_shadow_ 中转链——显示朝上而扭转正确。
    """
    bl_idname = "object.add_twist_bone"
    bl_label = "添加腕捩骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    finalize: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})  # type: ignore

    twist_bones_def = [
        ("左腕",  ["左腕捩", "左腕捩1", "左腕捩2", "左腕捩3"]),
        ("左ひじ", ["左手捩", "左手捩1", "左手捩2", "左手捩3"]),
        ("右腕",  ["右腕捩", "右腕捩1", "右腕捩2", "右腕捩3"]),
        ("右ひじ", ["右手捩", "右手捩1", "右手捩2", "右手捩3"]),
    ]
    _POS = {0: 0.80, 1: 0.20, 2: 0.40, 3: 0.60}
    _AXIS_SRC = {"腕捩": ("腕", "ひじ"), "手捩": ("ひじ", "手首")}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选择一个骨架对象")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones
        for bone_name, twist_names in self.twist_bones_def:
            if bone_name not in edit_bones:
                continue
            base_bone = edit_bones[bone_name]
            children_bones = [c for c in edit_bones if c.parent == base_bone]
            bone_head = base_bone.head.copy()
            bone_vec = base_bone.tail - base_bone.head
            length = bone_vec.length
            if length < 1e-6:
                continue
            dirn = bone_vec.normalized()
            seg_len = max(length * 0.12, 1e-4)
            roll = base_bone.roll

            created = {}
            for i, tname in enumerate(twist_names):
                tb = edit_bones.get(tname) or edit_bones.new(tname)
                h = bone_head + bone_vec * self._POS[i]
                tb.head = h
                if i == 0:
                    # main twist: along the arm axis (keeps the twist axis for fixed_axis)
                    tb.tail = h + dirn * seg_len
                    tb.roll = roll
                else:
                    # subs: vertical (world +Z), like the target PMX display; misaligned
                    # with the along-arm main so mmd_tools builds the _dummy_/_shadow_ relay.
                    tb.tail = h + Vector((0.0, 0.0, seg_len))
                    tb.align_roll(Vector((0.0, -1.0, 0.0)))
                tb.use_connect = False
                tb.parent = base_bone
                tb.use_deform = True
                created[tname] = tb

            # the base's deform children (ひじ/手首) hang under the main twist so they follow it
            main_tb = created[twist_names[0]]
            for child in children_bones:
                oh, ot = child.head.copy(), child.tail.copy()
                child.parent = main_tb
                child.use_connect = False
                child.head, child.tail = oh, ot

        bpy.ops.object.mode_set(mode='OBJECT')
        split_twist_weights(obj)
        self._fix_twist_axis(obj)
        _regroup(obj)
        if self.finalize:
            _finalize(obj)
        self.report({'INFO'}, "已设置捩骨：几何 + 权重守恒切分 + 轴固定")
        return {'FINISHED'}

    def _fix_twist_axis(self, obj):
        """Lock the main twist bones to their arm axis (fixed_axis) + rotate-only.

        fixed_axis (the target rig has it, the naive build lacks it) keeps the large
        VMD twist rotation purely about the bone axis; without it the non-twist
        component would propagate through 付与 to the upper arm and distort it.
        """
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        pose_bones = obj.pose.bones
        bones = obj.data.bones
        for side in ('左', '右'):
            for stem in ('腕捩', '手捩'):
                main_pb = pose_bones.get(f"{side}{stem}")
                if main_pb is None:
                    continue
                a_name, b_name = self._AXIS_SRC[stem]
                ba = bones.get(f"{side}{a_name}")
                bb = bones.get(f"{side}{b_name}")
                if ba and bb:
                    axis = (bb.head_local - ba.head_local)
                    if axis.length > 1e-6:
                        axis = axis.normalized()
                        mb = main_pb.mmd_bone
                        mb.enabled_fixed_axis = True
                        # mmd_bone.fixed_axis stores MMD coords = Blender (x, z, -y)
                        mb.fixed_axis = (axis.x, axis.z, -axis.y)
                main_pb.lock_location = (True, True, True)
                main_pb.lock_rotation = (True, False, True)
                for i in (1, 2, 3):
                    sub = pose_bones.get(f"{side}{stem}{i}")
                    if sub:
                        sub.lock_location = (True, True, True)


# ============================================================
# Leg D bones
# ============================================================

class OBJECT_OT_add_leg_d_bones(bpy.types.Operator):
    """添加 MMD 腿部 D 骨骼（几何 + 顶点组改名；付与/中转由 mmd_tools 统一建）。

    D 骨是平行的变形链（足D→下半身, ひざD→足D, 足首D→ひざD），网格权重从 足/ひざ/足首
    改名到对应 D 骨。D 骨竖直短桩、与沿腿的源骨不对齐 → apply_additional_transform 自动
    建 _dummy_/_shadow_ 中转（与旧手搭实现等价，但不再手写约束）。
    """
    bl_idname = "object.add_leg_d_bones"
    bl_label = "添加腿部D骨骼"

    finalize: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})  # type: ignore

    # (D bone, source bone, parent)  — parallel deform chain
    _D_CHAIN = [
        ("右足D", "右足", "下半身"), ("右ひざD", "右ひざ", "右足D"), ("右足首D", "右足首", "右ひざD"),
        ("左足D", "左足", "下半身"), ("左ひざD", "左ひざ", "左足D"), ("左足首D", "左足首", "左ひざD"),
    ]
    _TOE = [("右足先EX", "右足首D"), ("左足先EX", "左足首D")]

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个骨架")
            return {'CANCELLED'}

        existing = [b.name for b in obj.data.bones
                    if b.name.endswith('D') and ('足' in b.name or 'ひざ' in b.name)]
        if existing:
            self.report({'INFO'}, f"已经存在D骨骼: {', '.join(existing)}，跳过操作")
            return {'CANCELLED'}

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')
        eb = obj.data.edit_bones

        n = 0
        for d_name, src_name, parent_name in self._D_CHAIN:
            src = eb.get(src_name)
            parent = eb.get(parent_name)
            if not src or not parent:
                continue
            d = eb.get(d_name) or eb.new(d_name)
            d.head = src.head.copy()
            d.tail = src.head + Vector((0, 0, 0.1))
            d.use_connect = False
            d.parent = parent
            d.use_deform = True
            n += 1
        # toe-EX reparents under 足首D
        for toe_name, parent_name in self._TOE:
            toe = eb.get(toe_name)
            parent = eb.get(parent_name)
            if toe and parent:
                oh, ot = toe.head.copy(), toe.tail.copy()
                toe.parent = parent
                toe.use_connect = False
                toe.head, toe.tail = oh, ot

        bpy.ops.object.mode_set(mode='OBJECT')

        # mesh follows the D bones: rename the source vertex groups to the D names.
        from .weights.common import skinned_meshes
        for d_name, src_name, _ in self._D_CHAIN:
            for mesh in skinned_meshes(obj):
                vg = mesh.vertex_groups.get(src_name)
                if vg and not mesh.vertex_groups.get(d_name):
                    vg.name = d_name
        # lock D-bone location (rotation-only deform helpers)
        for d_name, _, _ in self._D_CHAIN:
            pb = obj.pose.bones.get(d_name)
            if pb:
                pb.lock_location = (True, True, True)

        _regroup(obj)
        if self.finalize:
            _finalize(obj)
        self.report({'INFO'}, f"已添加 {n} 个腿部D骨骼")
        return {'FINISHED'}


# ============================================================
# Shoulder P/C bones
# ============================================================

class OBJECT_OT_add_shoulder_p_bones(bpy.types.Operator):
    """添加 MMD 肩P骨骼（几何 + 重父级；付与/中转由 mmd_tools 统一建）。

    肩P 插在 上半身2 与 肩 之间；肩C 插在 肩 与 腕 之间，付与 肩C←肩P(-1) 抵消肩P。
    肩P/肩C 同为竖直短桩、互相对齐 → apply_additional_transform 直接建本地约束(无需中转骨)。
    """
    bl_idname = "object.add_shoulder_p_bones"
    bl_label = "添加肩P骨骼"

    finalize: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})  # type: ignore

    # (肩, 肩P, 肩C, 腕)
    _CONFIG = [("右肩", "右肩P", "右肩C", "右腕"), ("左肩", "左肩P", "左肩C", "左腕")]
    _UP = Vector((0, 0, 0.08))

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个骨架")
            return {'CANCELLED'}

        if any('肩P' in b.name for b in obj.data.bones):
            self.report({'INFO'}, "已经存在肩P骨骼，跳过操作")
            return {'CANCELLED'}

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')
        eb = obj.data.edit_bones
        upper2 = eb.get("上半身2")

        n = 0
        for sh_name, p_name, c_name, arm_name in self._CONFIG:
            sh = eb.get(sh_name)
            if not sh:
                continue
            head_pos = sh.head.copy()
            tail_pos = sh.tail.copy()

            p = eb.new(p_name)
            p.head = head_pos
            p.tail = head_pos + self._UP
            p.parent = upper2 if upper2 else sh.parent
            p.use_connect = False

            c = eb.new(c_name)
            c.head = tail_pos
            c.tail = tail_pos + self._UP
            c.parent = sh           # 肩C under 肩 (cancels 肩P for the arm below it)
            c.use_connect = False

            sh.parent = p           # 肩 under 肩P
            sh.use_connect = False

            arm = eb.get(arm_name)
            if arm:
                ah, at = arm.head.copy(), arm.tail.copy()
                arm.parent = c      # 腕 under 肩C
                arm.use_connect = False
                arm.head, arm.tail = ah, at
            n += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        for _, _, c_name, _ in self._CONFIG:
            pb = obj.pose.bones.get(c_name)
            if pb:
                pb.lock_location = (True, True, True)

        _regroup(obj)
        if self.finalize:
            _finalize(obj)
        self.report({'INFO'}, f"已添加 {n} 组肩P骨骼")
        return {'FINISHED'}
