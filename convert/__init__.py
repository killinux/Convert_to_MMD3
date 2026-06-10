"""Conversion engine — registers every bone operator (bl_idnames unchanged)."""

import bpy

from .identify import OBJECT_OT_auto_identify_skeleton
from .correct import OBJECT_OT_correct_bones
from .rename import OBJECT_OT_rename_to_mmd
from .complete import OBJECT_OT_complete_missing_bones
from .align import (
    OBJECT_OT_fix_forearm_bend,
    OBJECT_OT_align_arms_to_canonical,
    OBJECT_OT_align_fingers_to_canonical,
)
from .ik import OBJECT_OT_add_ik
from .groups import OBJECT_OT_create_bone_group
from .mmd_convert import OBJECT_OT_use_mmd_tools_convert
from .semistandard import (
    OBJECT_OT_add_twist_bone,
    OBJECT_OT_add_leg_d_bones,
    OBJECT_OT_add_shoulder_p_bones,
)
from .grants import OBJECT_OT_setup_mmd_grants
from .weights.transfer import OBJECT_OT_transfer_unused_weights
from .weights.palm import OBJECT_OT_fix_palm_weights
from .weights.sanitize import OBJECT_OT_sanitize_weights
from .pipeline import OBJECT_OT_one_click_convert


_CLASSES = (
    OBJECT_OT_auto_identify_skeleton,
    OBJECT_OT_correct_bones,
    OBJECT_OT_rename_to_mmd,
    OBJECT_OT_complete_missing_bones,
    OBJECT_OT_fix_forearm_bend,
    OBJECT_OT_align_arms_to_canonical,
    OBJECT_OT_align_fingers_to_canonical,
    OBJECT_OT_add_ik,
    OBJECT_OT_create_bone_group,
    OBJECT_OT_use_mmd_tools_convert,
    OBJECT_OT_add_twist_bone,
    OBJECT_OT_add_leg_d_bones,
    OBJECT_OT_add_shoulder_p_bones,
    OBJECT_OT_setup_mmd_grants,
    OBJECT_OT_transfer_unused_weights,
    OBJECT_OT_fix_palm_weights,
    OBJECT_OT_sanitize_weights,
    OBJECT_OT_one_click_convert,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
