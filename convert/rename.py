"""Step 1 — 重命名为 MMD: back up, auto-scale, rename mapped bones to MMD names."""

import bpy

from .. import bone_map_and_group
from .. import bone_utils
from ..presets import get_bones_list, auto_detect_upper_body_chain


class OBJECT_OT_rename_to_mmd(bpy.types.Operator):
    """将选定的骨骼重命名为 MMD 格式"""
    bl_idname = "object.rename_to_mmd"
    bl_label = "Rename to MMD"

    mmd_bone_map = bone_map_and_group.mmd_bone_map

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "没有选择骨架对象")
            return {'CANCELLED'}

        backup_data = obj.data.copy()
        backup_data.name = f"{obj.data.name}_backup"
        backup_obj = bpy.data.objects.new(f"{obj.name}_backup", backup_data)
        bpy.context.collection.objects.link(backup_obj)
        backup_obj.matrix_world = obj.matrix_world
        backup_obj.hide_viewport = True
        backup_obj.hide_render = True
        self.report({'INFO'}, f"已创建骨架备份: {backup_obj.name} (数据块: {backup_obj.data.name})")

        scaled, scale_factor, skeleton_height = bone_utils.check_and_scale_skeleton(obj)
        if scaled:
            self.report({'INFO'}, f"骨架高度为 {skeleton_height:.2f}m，已缩放 {scale_factor:.3f} 倍")

        scene = context.scene
        has_bone_set = any(getattr(scene, p, None) for p in get_bones_list())
        if not has_bone_set:
            self.report({'WARNING'}, "未设置骨骼")
            return {'CANCELLED'}

        # Detect the upper-body chain before rename, using the original names.
        auto_detect_upper_body_chain(scene, obj)

        for prop_name, new_name in self.mmd_bone_map.items():
            bone_name = getattr(scene, prop_name, None)
            if not bone_name:
                continue
            bone = obj.pose.bones.get(bone_name)
            if not bone:
                self.report({'WARNING'}, f"未找到骨骼 '{bone_name}' 以重命名为 {new_name}")
                continue
            if bone.name != new_name:
                bone.name = new_name
                setattr(scene, prop_name, new_name)

        # Re-detect with MMD names so the chain props match the renamed bones.
        auto_detect_upper_body_chain(scene, obj)

        bpy.context.object.data.show_names = True
        return {'FINISHED'}
