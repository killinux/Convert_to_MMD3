"""Slim 'Convert to MMD' panel — bone management only (no physics/import/dev-tools).

Keeps the original 主骨骼管理 layout and every bl_idname so the operation surface is
unchanged (req 5). The 次标准 tab lists only the bone operators kept in this build.
"""

import bpy


def _bone_row(layout, scene, obj, label_text, prop_name):
    row = layout.row(align=True)
    split = row.split(factor=0.1, align=True)
    split.label(text=label_text)
    act = split.split(factor=1)
    sub = act.split(factor=(0.49 * 0.1), align=True)
    sub.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = prop_name
    sub.prop_search(scene, prop_name, obj.data, "bones", text="")


def _symmetric_row(layout, scene, obj, label_text, left_prop, right_prop):
    row = layout.row(align=True)
    split = row.split(factor=0.1, align=True)
    split.label(text=label_text)
    act = split.split(factor=1, align=True)
    left = act.split(factor=0.49, align=True)
    lrow = left.column(align=True).row(align=True)
    lb = lrow.split(factor=0.1, align=True)
    lb.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = left_prop
    lb.prop_search(scene, left_prop, obj.data, "bones", text="")
    divider = left.split(factor=(0.02 / (0.02 + 0.49)), align=True)
    divider.label(text="|")
    right = divider.split(factor=1, align=True)
    rrow = right.column(align=True).row(align=True)
    rb = rrow.split(factor=0.1, align=True)
    rb.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = right_prop
    rb.prop_search(scene, right_prop, obj.data, "bones", text="")


def _finger_row(layout, scene, obj, label_text, p1, p2, p3):
    divider_ratio = 0.02
    split_ratio = (1 - 2 * divider_ratio) / 3
    row = layout.row(align=True)
    split = row.split(factor=0.1, align=True)
    split.label(text=label_text)
    act = split.split(factor=1, align=True)

    first = act.split(factor=split_ratio, align=True)
    f1 = first.column(align=True).row(align=True).split(factor=0.1, align=True)
    f1.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = p1
    f1.prop_search(scene, p1, obj.data, "bones", text="")
    d1 = first.split(factor=divider_ratio / (1 - split_ratio), align=True)
    d1.label(text="|")
    second = d1.split(factor=split_ratio / (1 - split_ratio - divider_ratio), align=True)
    f2 = second.column(align=True).row(align=True).split(factor=0.1, align=True)
    f2.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = p2
    f2.prop_search(scene, p2, obj.data, "bones", text="")
    d2 = second.split(factor=divider_ratio / (1 - split_ratio * 2 - divider_ratio), align=True)
    d2.label(text="|")
    third = d2.split(factor=1, align=True)
    f3 = third.column(align=True).row(align=True).split(factor=0.1, align=True)
    f3.operator("object.fill_from_selection_specific", text="", icon='ZOOM_SELECTED').bone_property = p3
    f3.prop_search(scene, p3, obj.data, "bones", text="")


class OBJECT_PT_skeleton_hierarchy(bpy.types.Panel):
    bl_label = "Convert to MMD"
    bl_idname = "OBJECT_PT_convert_to_mmd"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Convert to MMD"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            layout.label(text="请选中骨架对象", icon='INFO')
            layout.menu("TOPBAR_MT_file_import", text="导入模型", icon='IMPORT')
            return

        row = layout.row()
        row.prop(scene, "my_enum", expand=True)

        if scene.my_enum == 'option1':
            box = layout.box()
            box.label(text="自动 / 一键", icon='AUTO')
            r = box.row(align=True)
            r.scale_y = 1.35
            r.operator("object.one_click_convert", text="一键转换 XPS→MMD", icon='PLAY')
            box.operator("object.auto_identify_skeleton", text="自动识别骨架（填充下方槽位）", icon='ZOOM_SELECTED')

            r = layout.row(align=True)
            r.prop(scene, "preset_enum", text="")
            r.operator("object.import_preset", text="导入预设")
            r.operator("object.export_preset", text="导出预设")
            r.operator("object.clear_bone_selection", text="", icon='X')

            main_col = layout.column(align=True)
            col = main_col.box().column()
            _bone_row(col, scene, obj, "操作中心", "control_center_bone")
            _bone_row(col, scene, obj, "全ての親", "all_parents_bone")
            _bone_row(col, scene, obj, "センター", "center_bone")
            _bone_row(col, scene, obj, "グルーブ", "groove_bone")
            _bone_row(col, scene, obj, "腰", "hip_bone")

            col = main_col.box().column()
            _bone_row(col, scene, obj, "上半身*", "upper_body_bone")
            _bone_row(col, scene, obj, "首*", "neck_bone")
            _bone_row(col, scene, obj, "頭*", "head_bone")
            _symmetric_row(col, scene, obj, "目", "left_eye_bone", "right_eye_bone")
            _symmetric_row(col, scene, obj, "肩*", "left_shoulder_bone", "right_shoulder_bone")
            _symmetric_row(col, scene, obj, "腕*", "left_upper_arm_bone", "right_upper_arm_bone")
            _symmetric_row(col, scene, obj, "ひじ*", "left_lower_arm_bone", "right_lower_arm_bone")
            _symmetric_row(col, scene, obj, "手首*", "left_hand_bone", "right_hand_bone")

            col = main_col.box().column()
            _bone_row(col, scene, obj, "下半身", "lower_body_bone")
            _symmetric_row(col, scene, obj, "足*", "left_thigh_bone", "right_thigh_bone")
            _symmetric_row(col, scene, obj, "ひざ*", "left_calf_bone", "right_calf_bone")
            _symmetric_row(col, scene, obj, "足首*", "left_foot_bone", "right_foot_bone")
            _symmetric_row(col, scene, obj, "足先EX", "left_toe_bone", "right_toe_bone")

            col = main_col.box().column()
            for label, a, b, c in (
                ("左親指", "left_thumb_0", "left_thumb_1", "left_thumb_2"),
                ("左人指", "left_index_1", "left_index_2", "left_index_3"),
                ("左中指", "left_middle_1", "left_middle_2", "left_middle_3"),
                ("左薬指", "left_ring_1", "left_ring_2", "left_ring_3"),
                ("左小指", "left_pinky_1", "left_pinky_2", "left_pinky_3"),
                ("右親指", "right_thumb_0", "right_thumb_1", "right_thumb_2"),
                ("右人指", "right_index_1", "right_index_2", "right_index_3"),
                ("右中指", "right_middle_1", "right_middle_2", "right_middle_3"),
                ("右薬指", "right_ring_1", "right_ring_2", "right_ring_3"),
                ("右小指", "right_pinky_1", "right_pinky_2", "right_pinky_3"),
            ):
                _finger_row(col, scene, obj, label, a, b, c)

            layout.operator("object.correct_bones", text="归正骨架位置")
            row = layout.row()
            row.operator("object.rename_to_mmd", text="1.重命名为MMD")
            row.operator("object.complete_missing_bones", text="2.补全缺失骨骼")
            row = layout.row()
            row.operator("object.add_mmd_ik", text="3.添加MMD IK")
            row.operator("object.create_bone_group", text="4.创建骨骼集合")
            layout.operator("object.use_mmd_tools_convert", text="5.使用mmdtools转换格式")

        else:
            box = layout.box()
            box.label(text="次标准骨骼", icon='BONE_DATA')
            box.operator("object.add_leg_d_bones", text="添加腿部D骨骼", icon='BONE_DATA')
            box.operator("object.add_twist_bone", text="添加捩骨骼", icon='BONE_DATA')
            box.operator("object.add_shoulder_p_bones", text="添加肩P骨骼", icon='BONE_DATA')

            box = layout.box()
            box.label(text="XPS 专项修正 / 权重", icon='MODIFIER')
            box.operator("object.transfer_unused_weights", text="转移 unused 骨权重", icon='MOD_VERTEX_WEIGHT')
            box.operator("object.fix_forearm_bend", text="修正前腕弯曲", icon='BONE_DATA')
            r = box.row(align=True)
            r.operator("object.align_arms_to_canonical", text="对齐上臂", icon='BONE_DATA')
            r.operator("object.align_fingers_to_canonical", text="对齐手指", icon='BONE_DATA')
            box.operator("object.fix_palm_weights", text="手部权重修正(拇指+掌骨)", icon='MOD_VERTEX_WEIGHT')
            box.operator("object.sanitize_weights", text="权重收尾(剔渣+4骨+归一)", icon='MOD_VERTEX_WEIGHT')
            box.operator("object.setup_mmd_grants", text="设置标准付与(导出PMX前)", icon='CONSTRAINT')


def register():
    bpy.utils.register_class(OBJECT_PT_skeleton_hierarchy)


def unregister():
    bpy.utils.unregister_class(OBJECT_PT_skeleton_hierarchy)
