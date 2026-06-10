"""Step 4 — 创建骨骼集合: build bone collections (4.0+) or bone groups (3.x)."""

import bpy
from bpy.props import BoolProperty
from functools import lru_cache


@lru_cache(maxsize=None)
def load_bone_presets():
    from ..bone_map_and_group import mmd_bone_group
    all_bones = set()
    try:
        valid_groups = [g for g in mmd_bone_group
                        if isinstance(g, dict) and 'name' in g and isinstance(g.get('bones'), list)]
        if not valid_groups:
            raise ValueError("bone_map_and_group.py中未找到有效的骨骼分组配置")
        preset_dict = {}
        group_visibility = {}
        for p in valid_groups:
            if p['name'] not in preset_dict:
                preset_dict[p['name']] = list({b.strip() for b in p['bones'] if b.strip()})
                group_visibility[p['name']] = p.get('visible', True)
        all_bones.update(*(p['bones'] for p in valid_groups))
        return preset_dict, all_bones, group_visibility
    except Exception as e:
        print(f"加载骨骼分组配置失败: {str(e)}")
    return {}, set(), {}


BONE_GROUP_PRESETS, PRESET_BONES, GROUP_VISIBILITY = load_bone_presets()


class OBJECT_OT_create_bone_group(bpy.types.Operator):
    bl_idname = "object.create_bone_group"
    bl_label = "创建骨骼集合"
    bl_description = "根据Blender版本自动创建骨骼组或骨骼集合"

    use_presets: BoolProperty(name="使用预设分组", default=True)  # type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未选择骨架对象")
            return {'CANCELLED'}
        if self.use_presets and not BONE_GROUP_PRESETS:
            self.report({'ERROR'}, "未找到有效的骨骼分组配置")
            return {'CANCELLED'}
        if hasattr(obj.data, 'collections'):
            self._create_bone_collections(obj)
        else:
            self._create_bone_groups(obj)
        return {'FINISHED'}

    def _create_bone_collections(self, obj):
        armature = obj.data
        bone_dict = {b.name: b for b in armature.bones}
        for coll in list(getattr(armature, 'collections', []) or []):
            armature.collections.remove(coll)
        remaining = set(bone_dict) - PRESET_BONES
        for group_name, bones in BONE_GROUP_PRESETS.items():
            valid = [b for b in bones if b in bone_dict]
            if valid:
                coll = armature.collections.new(group_name)
                coll.is_visible = GROUP_VISIBILITY.get(group_name, True)
                for b in valid:
                    coll.assign(bone_dict[b])
                remaining -= set(valid)
        if remaining:
            coll = armature.collections.new('other')
            coll.is_visible = True
            for b in remaining:
                coll.assign(bone_dict[b])

    def _create_bone_groups(self, obj):
        bone_dict = {b.name: b for b in obj.data.bones}
        to_create = [g for g in BONE_GROUP_PRESETS if g not in obj.pose.bone_groups]
        with bpy.context.temp_override(selected_objects=[obj], active_object=obj):
            for group_name in to_create:
                bpy.ops.pose.group_add()
                obj.pose.bone_groups[-1].name = group_name
        group_dict = {g.name: g for g in obj.pose.bone_groups}
        for group_name, bones in BONE_GROUP_PRESETS.items():
            if group_name in group_dict:
                for b in bones:
                    pose_bone = obj.pose.bones.get(b)
                    if pose_bone:
                        pose_bone.bone_group = group_dict[group_name]
        assigned = set()
        for group_bones in BONE_GROUP_PRESETS.values():
            assigned.update(group_bones)
        remaining = set(bone_dict) - assigned
        if remaining:
            other = group_dict.get('other') or obj.pose.bone_groups.new(name='other')
            for b in remaining:
                pose_bone = obj.pose.bones.get(b)
                if pose_bone:
                    pose_bone.bone_group = other
