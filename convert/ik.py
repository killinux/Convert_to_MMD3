"""Step 3 — 添加 MMD IK: 足ＩＫ/つま先ＩＫ chains + knee IK limits."""

import bpy
from mathutils import Vector
from math import radians
from .. import bone_utils


def _add_ik(bone, target, subtarget, chain_count, iterations,
            ik_min_x=None, ik_max_x=None, use_ik_limit_x=False,
            use_ik_limit_y=False, use_ik_limit_z=False):
    c = bone.constraints.new(type='IK')
    c.name = "IK"
    c.target = target
    c.subtarget = subtarget
    c.chain_count = chain_count
    c.iterations = iterations
    if ik_min_x is not None:
        bone.ik_min_x = ik_min_x
    if ik_max_x is not None:
        bone.ik_max_x = ik_max_x
    bone.use_ik_limit_x = use_ik_limit_x
    bone.use_ik_limit_y = use_ik_limit_y
    bone.use_ik_limit_z = use_ik_limit_z


def _add_limit_rotation(bone, use_limit_x=False, min_x=None, max_x=None):
    c = bone.constraints.new(type='LIMIT_ROTATION')
    c.name = "mmd_ik_limit_override"
    c.influence = 1
    c.use_limit_x = use_limit_x
    c.owner_space = 'LOCAL'
    if min_x is not None:
        c.min_x = min_x
    if max_x is not None:
        c.max_x = max_x


def _add_damped_track(bone, target, subtarget):
    c = bone.constraints.new(type='DAMPED_TRACK')
    c.name = "mmd_ik_target_override"
    c.target = target
    c.subtarget = subtarget
    c.influence = 0


class OBJECT_OT_add_ik(bpy.types.Operator):
    """为骨架添加MMD IK"""
    bl_idname = "object.add_mmd_ik"
    bl_label = "Add MMD IK"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "没有选择骨架对象")
            return {'CANCELLED'}

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        eb = obj.data.edit_bones
        if '全ての親' not in eb:
            self.report({'ERROR'}, "缺失 全ての親，请先补全骨骼")
            return {'CANCELLED'}

        # per-side: a model missing one (or both) legs degrades instead of dying
        sides = [s for s in ('左', '右') if f'{s}ひざ' in eb and f'{s}足首' in eb]
        if not sides:
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'WARNING'}, "无完整腿链，跳过 IK")
            return {'FINISHED'}

        bone_length = bone_utils.calculate_bone_length(eb)
        ik_bones = {}
        for s in sides:
            knee_tail = eb[f"{s}ひざ"].tail
            ankle_tail = eb[f"{s}足首"].tail
            ik_bones[f"{s}足IK親"] = {"head": Vector((knee_tail.x, knee_tail.y, 0)),
                                    "tail": knee_tail, "parent": "全ての親"}
            ik_bones[f"{s}足ＩＫ"] = {"head": knee_tail,
                                   "tail": knee_tail + Vector((0, bone_length * 0.5, 0)),
                                   "parent": f"{s}足IK親"}
            ik_bones[f"{s}つま先ＩＫ"] = {"head": ankle_tail,
                                      "tail": ankle_tail + Vector((0, 0, -bone_length * 0.4)),
                                      "parent": f"{s}足ＩＫ"}
        for name, p in ik_bones.items():
            bone_utils.create_or_update_bone(eb, name, p["head"], p["tail"],
                                             use_connect=False, parent_name=p["parent"], use_deform=False)

        bpy.ops.object.mode_set(mode='POSE')
        pb = obj.pose.bones
        for s in sides:
            _add_ik(pb[f"{s}ひざ"], obj, f"{s}足ＩＫ", 2, 200, ik_min_x=radians(0), ik_max_x=radians(180),
                    use_ik_limit_x=True, use_ik_limit_y=True, use_ik_limit_z=True)
            _add_limit_rotation(pb[f"{s}ひざ"], use_limit_x=True, min_x=radians(0.5), max_x=radians(180))
            _add_ik(pb[f"{s}足首"], obj, f"{s}つま先ＩＫ", 1, 200)
            _add_damped_track(pb[f"{s}足首"], obj, f"{s}ひざ")
        return {'FINISHED'}
