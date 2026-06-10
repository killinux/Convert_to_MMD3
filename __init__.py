bl_info = {
    "name": "Convert to MMD 2",
    "author": "UITCIS(空想幻灵)",
    "version": (3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Convert to MMD",
    "description": "Refactored bone-management engine: XPS→MMD skeleton conversion",
    "warning": "",
    "category": "Animation",
}

import os
import bpy

from . import encoding_patch
from . import properties
from . import presets
from . import ui
from . import convert


def register():
    encoding_patch.apply_encoding_patch()

    properties.register_properties(presets.get_bones_list())
    presets.register()
    convert.register()
    ui.register()

    bpy.types.Scene.preset_enum = bpy.props.EnumProperty(
        name="预设", description="选择一个预设",
        items=_get_preset_enum, update=_preset_enum_update)
    bpy.types.Scene.my_enum = bpy.props.EnumProperty(
        name="模式", description="选择操作模式",
        items=[
            ('option1', "主骨骼管理", "预设管理和主骨骼转换操作"),
            ('option2', "次标准骨骼管理", "次标准骨骼追加"),
        ],
        default='option1')


def unregister():
    encoding_patch.remove_encoding_patch()

    ui.unregister()
    convert.unregister()
    presets.unregister()
    properties.unregister_properties(properties.get_registered_props())

    for prop in ("preset_enum", "my_enum"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)


def _get_preset_enum(self, context):
    presets_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "presets")
    items = []
    if os.path.exists(presets_dir):
        for fn in os.listdir(presets_dir):
            if fn.endswith('.json') and not fn.startswith('canonical_'):
                name = os.path.splitext(fn)[0]
                items.append((name, name, ""))
    return items


def _preset_enum_update(self, context):
    bpy.ops.object.load_preset(preset_name=self.preset_enum)
    return None


if __name__ == "__main__":
    register()
