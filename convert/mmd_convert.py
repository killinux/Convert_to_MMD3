"""Step 5 — mmd_tools 转换: convert to an MMD model, then de-dup armature modifiers.

Reuses mmd_tools' own `convert_to_mmd_model` (req 2) for the heavy lifting (mmd_root,
materials, rigid/joint groups, per-bone mmd_bone data). The one fix-up we add is
removing the duplicate armature modifier: XNALaraMesh's import already added one and
convert_to_mmd_model adds a second → double skinning that explodes the mesh under pose.
"""

import bpy

from .weights.common import skinned_meshes


class OBJECT_OT_use_mmd_tools_convert(bpy.types.Operator):
    """调用mmdtools进行格式转换"""
    bl_idname = "object.use_mmd_tools_convert"
    bl_label = "Convert to MMD Model"
    bl_description = "使用mmd_tools插件转换模型格式（需要先安装mmd_tools插件）"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未选择骨架对象")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            bpy.ops.mmd_tools.convert_to_mmd_model(convert_material_nodes=False)
        except (TypeError, AttributeError):
            try:
                bpy.ops.mmd_tools.convert_to_mmd_model()
            except (TypeError, AttributeError):
                bpy.context.window_manager.popup_menu(
                    self._draw_error_menu, title="MMD Tools 未安装", icon='ERROR')
                return {'CANCELLED'}

        # De-dup: keep only the first armature modifier per mesh that targets `obj`.
        # Two modifiers → double skinning (identity at rest, doubles bone transforms
        # when posed → vertices fly apart).
        removed = 0
        for m in skinned_meshes(obj):
            arm_mods = [md for md in m.modifiers if md.type == 'ARMATURE' and md.object == obj]
            for md in arm_mods[1:]:
                m.modifiers.remove(md)
                removed += 1
        if removed:
            print(f"[mmd_convert] 移除 {removed} 个重复 armature 修改器（防止双重蒙皮炸网格）")

        context.view_layer.objects.active = obj
        obj.select_set(True)
        return {'FINISHED'}

    def _draw_error_menu(self, menu, context):
        layout = menu.layout
        layout.separator()
        layout.operator("wm.url_open", text="前往下载页面", icon='URL').url = \
            "https://extensions.blender.org/add-ons/mmd-tools/"
        layout.operator("wm.url_open", text="查看使用文档", icon='HELP').url = \
            "https://mmd-blender.fandom.com/wiki/MMD_Tools_Documentation"
