"""Bone-slot filling + preset load/import/export (drives the panel's mapping UI).

Ported from the original preset_operator. Pure slot bookkeeping — no conversion
logic. `use_mmd_tools_convert` moved to convert/mmd_convert.py.
"""

import bpy
import os
import json


_finger_bone_props = [
    ('left_thumb_0', 'left_thumb_1', 'left_thumb_2'),
    ('left_index_1', 'left_index_2', 'left_index_3'),
    ('left_middle_1', 'left_middle_2', 'left_middle_3'),
    ('left_ring_1', 'left_ring_2', 'left_ring_3'),
    ('left_pinky_1', 'left_pinky_2', 'left_pinky_3'),
    ('right_thumb_0', 'right_thumb_1', 'right_thumb_2'),
    ('right_index_1', 'right_index_2', 'right_index_3'),
    ('right_middle_1', 'right_middle_2', 'right_middle_3'),
    ('right_ring_1', 'right_ring_2', 'right_ring_3'),
    ('right_pinky_1', 'right_pinky_2', 'right_pinky_3'),
]

_symmetric_bone_rules = [
    ('Left', 'Right'), ('Right', 'Left'), ('L_', 'R_'), ('R_', 'L_'),
    ('-L', '-R'), ('-R', '-L'), ('.L', '.R'), ('.R', '.L'),
    ('_L', '_R'), ('_R', '_L'), ('左', '右'), ('右', '左'), (' L', ' R'),
]

_left_right_mapping = {
    'left_thumb_0': 'right_thumb_0', 'left_index_1': 'right_index_1',
    'left_middle_1': 'right_middle_1', 'left_ring_1': 'right_ring_1',
    'left_pinky_1': 'right_pinky_1', 'right_thumb_0': 'left_thumb_0',
    'right_index_1': 'left_index_1', 'right_middle_1': 'left_middle_1',
    'right_ring_1': 'left_ring_1', 'right_pinky_1': 'left_pinky_1',
    'left_eye_bone': 'right_eye_bone', 'right_eye_bone': 'left_eye_bone',
    'left_shoulder_bone': 'right_shoulder_bone', 'right_shoulder_bone': 'left_shoulder_bone',
    'left_upper_arm_bone': 'right_upper_arm_bone', 'right_upper_arm_bone': 'left_upper_arm_bone',
    'left_lower_arm_bone': 'right_lower_arm_bone', 'right_lower_arm_bone': 'left_lower_arm_bone',
    'left_hand_bone': 'right_hand_bone', 'right_hand_bone': 'left_hand_bone',
    'left_thigh_bone': 'right_thigh_bone', 'right_thigh_bone': 'left_thigh_bone',
    'left_calf_bone': 'right_calf_bone', 'right_calf_bone': 'left_calf_bone',
    'left_foot_bone': 'right_foot_bone', 'right_foot_bone': 'left_foot_bone',
    'left_toe_bone': 'right_toe_bone', 'right_toe_bone': 'left_toe_bone',
}


def get_bones_list():
    """Bone property-name → default ("") map driving the dynamic scene props."""
    from .bone_map_and_group import mmd_bone_map
    return {k: "" for k in mmd_bone_map.keys()}


def get_upper_body_chain_props():
    return ['upper_body2_bone', 'upper_body3_bone', 'upper_body4_bone', 'upper_body5_bone']


def auto_detect_upper_body_chain(scene, armature):
    """Fill 上半身2.. by walking 首.parent up to 上半身."""
    upper_body_name = getattr(scene, "upper_body_bone", "")
    neck_name = getattr(scene, "neck_bone", "")
    if not upper_body_name or not neck_name or armature.type != 'ARMATURE':
        return False
    bones = armature.data.bones
    if not bones.get(upper_body_name) or not bones.get(neck_name):
        return False
    chain = []
    current = bones[neck_name].parent
    while current:
        if current.name == upper_body_name:
            break
        chain.append(current.name)
        current = current.parent
    if not current or current.name != upper_body_name:
        return False
    chain.reverse()
    prop_names = get_upper_body_chain_props()
    for i, bone_name in enumerate(chain):
        if i < len(prop_names):
            setattr(scene, prop_names[i], bone_name)
    for i in range(len(chain), len(prop_names)):
        setattr(scene, prop_names[i], "")
    return len(chain) > 0


def auto_fill_finger_bones(scene, armature, first_prop):
    """Fill a finger chain (and its mirror) from the first joint."""
    for fp, second_prop, third_prop in _finger_bone_props:
        if fp != first_prop:
            continue
        mode = bpy.context.mode
        first_value = getattr(scene, first_prop, "")
        source = armature.data.edit_bones if mode == 'EDIT_ARMATURE' else (
            armature.pose.bones if mode == 'POSE' else None)
        if source is None:
            return False
        first_bone = source.get(first_value)
        if first_bone and len(first_bone.children) > 0:
            second_bone = first_bone.children[0].name
            setattr(scene, second_prop, second_bone)
            second_node = source.get(second_bone)
            if second_node and len(second_node.children) > 0:
                setattr(scene, third_prop, second_node.children[0].name)
                try_fill_symmetric_bones(scene, armature, first_prop, mode)
                return True
        return False
    return False


def try_fill_symmetric_bones(scene, armature, first_prop, mode):
    symmetric_prop = _left_right_mapping.get(first_prop)
    if not symmetric_prop or getattr(scene, symmetric_prop, ""):
        return False
    first_value = getattr(scene, first_prop, "")
    if not first_value:
        return False
    symmetric_name = None
    for old_str, new_str in _symmetric_bone_rules:
        if old_str in first_value:
            symmetric_name = first_value.replace(old_str, new_str)
            break
    if not symmetric_name:
        return False
    source = armature.data.edit_bones if mode == 'EDIT_ARMATURE' else (
        armature.pose.bones if mode == 'POSE' else None)
    if source is None or symmetric_name not in source:
        return False
    symmetric_bone = source.get(symmetric_name)
    if not symmetric_bone:
        return False
    setattr(scene, symmetric_prop, symmetric_name)
    if '_0' in first_prop or '_1' in first_prop or '_2' in first_prop:
        _fill_symmetric_finger_chain(scene, armature, symmetric_prop, symmetric_bone, mode)
    return True


def _fill_symmetric_finger_chain(scene, armature, symmetric_prop, symmetric_bone, mode):
    if '_0' in symmetric_prop:
        second_prop = symmetric_prop.replace('_0', '_1')
        third_prop = symmetric_prop.replace('_0', '_2')
    elif '_1' in symmetric_prop:
        second_prop = symmetric_prop.replace('_1', '_2')
        third_prop = symmetric_prop.replace('_1', '_3')
    else:
        second_prop = third_prop = symmetric_prop
    source = armature.data.edit_bones if mode == 'EDIT_ARMATURE' else armature.pose.bones
    if symmetric_bone and len(symmetric_bone.children) > 0:
        setattr(scene, symmetric_prop, symmetric_bone.name)
        second_bone = symmetric_bone.children[0].name
        setattr(scene, second_prop, second_bone)
        second_node = source.get(second_bone)
        if second_node and len(second_node.children) > 0:
            setattr(scene, third_prop, second_node.children[0].name)


def check_single_bone_position(armature, bone_name, is_left, mode):
    """Warn if a left/right slot was filled with a bone on the wrong side."""
    if mode == 'EDIT_ARMATURE':
        bone = armature.data.edit_bones.get(bone_name)
    elif mode == 'POSE':
        bone = armature.pose.bones.get(bone_name)
    else:
        return True, ""
    if not bone:
        return True, ""
    bone_x = bone.head[0]
    if is_left and bone_x <= 0:
        return False, f"警告：你选择的骨骼可能是右侧骨骼（X={bone_x:.2f} 应为正值）"
    if not is_left and bone_x >= 0:
        return False, f"警告：你选择的骨骼可能是左侧骨骼（X={bone_x:.2f} 应为负值）"
    return True, ""


class OBJECT_OT_fill_from_selection_specific(bpy.types.Operator):
    """从当前选定的骨骼填充特定的骨骼属性"""
    bl_idname = "object.fill_from_selection_specific"
    bl_label = "Fill from Selection Specific"

    bone_property: bpy.props.StringProperty(name="Bone Property")  # type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未选择骨架对象")
            return {'CANCELLED'}
        scene = context.scene
        mode = context.mode
        if mode == 'POSE':
            selected = [b.name for b in (context.selected_pose_bones or [])]
        elif mode == 'EDIT_ARMATURE':
            selected = [b.name for b in obj.data.edit_bones if b.select]
        else:
            self.report({'ERROR'}, "请在姿态模式或编辑模式下选择骨骼")
            return {'CANCELLED'}
        if not selected:
            self.report({'ERROR'}, "未选择骨骼")
            return {'CANCELLED'}

        setattr(scene, self.bone_property, selected[0])
        if self.bone_property in _left_right_mapping:
            is_left = self.bone_property.startswith('left_')
            ok, msg = check_single_bone_position(obj, selected[0], is_left, mode)
            if not ok:
                self.report({'WARNING'}, msg)

        if auto_fill_finger_bones(scene, obj, self.bone_property):
            self.report({'INFO'}, "已自动填充指骨链")
        if self.bone_property in ('upper_body_bone', 'neck_bone'):
            auto_detect_upper_body_chain(scene, obj)
        return {'FINISHED'}


class OBJECT_OT_export_preset(bpy.types.Operator):
    """导出当前骨骼配置为预设"""
    bl_idname = "object.export_preset"
    bl_label = "Export Preset"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene
        preset = {p: getattr(scene, p, "") for p in get_bones_list()}
        with open(self.filepath, 'w') as f:
            json.dump(preset, f, indent=4)
        self.report({'INFO'}, f"预设已导出到 {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        self.filepath = bpy.path.ensure_ext("CTMMD", ".json")
        return {'RUNNING_MODAL'}


class OBJECT_OT_import_preset(bpy.types.Operator):
    """导入骨骼配置预设"""
    bl_idname = "object.import_preset"
    bl_label = "Import Preset"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene
        try:
            with open(self.filepath, 'r') as f:
                preset = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"加载预设失败：{str(e)}")
            return {'CANCELLED'}
        bones = get_bones_list()
        for prop_name, value in preset.items():
            if prop_name in bones:
                setattr(scene, prop_name, value)
        self.report({'INFO'}, f"已从 {self.filepath} 导入预设")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        self.filter_glob = "*.json"
        return {'RUNNING_MODAL'}


class OBJECT_OT_clear_bone_selection(bpy.types.Operator):
    """清空所有骨骼选择框中的内容"""
    bl_idname = "object.clear_bone_selection"
    bl_label = "清空骨骼选择"
    bl_description = "清空所有骨骼选择框中的内容"

    def execute(self, context):
        scene = context.scene
        for prop_name in get_bones_list():
            if hasattr(scene, prop_name):
                setattr(scene, prop_name, "")
        self.report({'INFO'}, "已清空所有骨骼选择")
        return {'FINISHED'}


class OBJECT_OT_load_preset(bpy.types.Operator):
    """加载内置预设并自动检测上半身链"""
    bl_idname = "object.load_preset"
    bl_label = "Load Preset"

    preset_name: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        presets_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "presets")
        preset_path = os.path.join(presets_dir, f"{self.preset_name}.json")
        if os.path.exists(preset_path):
            with open(preset_path, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            for prop_name, bone_name in preset_data.items():
                if hasattr(context.scene, prop_name):
                    setattr(context.scene, prop_name, bone_name)
        obj = context.active_object
        if obj and obj.type == 'ARMATURE':
            auto_detect_upper_body_chain(context.scene, obj)
        return {'FINISHED'}


_CLASSES = (
    OBJECT_OT_fill_from_selection_specific,
    OBJECT_OT_export_preset,
    OBJECT_OT_import_preset,
    OBJECT_OT_clear_bone_selection,
    OBJECT_OT_load_preset,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
