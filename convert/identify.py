"""Step 0 — auto-identify skeleton bone roles by topology + geometry (no presets)."""

import bpy
from collections import Counter

from ..skeleton_identifier import identify_skeleton, clear_cache
from ..helper_classifier import classify_helpers
from ..bone_map_and_group import mmd_bone_map
from ..presets import auto_detect_upper_body_chain


class OBJECT_OT_auto_identify_skeleton(bpy.types.Operator):
    """自动识别骨架角色（纯拓扑+几何，不依赖骨名/预设）"""
    bl_idname = "object.auto_identify_skeleton"
    bl_label = "Auto Identify Skeleton"
    bl_description = "分析骨架拓扑与几何，自动填充各 MMD 骨骼槽位（无需预设）"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未选择骨架对象")
            return {'CANCELLED'}

        # identify reads bone positions in armature-data space; an object-level
        # rotation/scale (some import paths leave one) would break the Z-up /
        # ±X-lateral assumptions — bake it first.
        try:
            mw = obj.matrix_world
            needs_apply = any(
                abs(mw[i][j] - (1.0 if i == j else 0.0)) > 1e-5
                for i in range(3) for j in range(3))
            if needs_apply:
                from ..bone_utils import apply_armature_transforms
                if apply_armature_transforms(context, obj):
                    print("[Auto Identify] 已应用骨架对象旋转/缩放")
        except Exception as e:
            print(f"[Auto Identify] transform-apply 检查失败: {e}")

        clear_cache()
        mapping = identify_skeleton(obj.data)
        cls = classify_helpers(obj.data, mapping)

        scene = context.scene
        for prop_name, bone_name in mapping.items():
            if bone_name and hasattr(scene, prop_name):
                setattr(scene, prop_name, bone_name)

        try:
            auto_detect_upper_body_chain(scene, obj)
        except Exception as e:
            print(f"[Auto Identify] auto_detect_upper_body_chain: {e}")

        print("\n========== [Auto Identify] 骨架自动识别结果 ==========")
        matched, unmatched = [], []
        for prop_name, mmd_name in mmd_bone_map.items():
            xps_name = mapping.get(prop_name, "") or getattr(scene, prop_name, "")
            (matched if xps_name else unmatched).append(
                f"  {mmd_name:10s} ← {xps_name or '(未匹配)'}")
        print(f"--- 已匹配 ({len(matched)}) ---")
        for line in matched:
            print(line)
        if unmatched:
            print(f"--- 未匹配 ({len(unmatched)}) — 需手动设置或由补全骨骼创建 ---")
            for line in unmatched:
                print(line)

        print("\n--- Helper 骨分类 ---")
        for cat in ("twist", "pelvis", "preserve", "merge", "other"):
            names = sorted(k for k, v in cls.items() if v == cat)
            if names:
                preview = ", ".join(names[:5])
                if len(names) > 5:
                    preview += f" (+{len(names) - 5})"
                print(f"  {cat:10s} {len(names):3d}  {preview}")
        print("=" * 50)

        total = sum(1 for v in mapping.values() if v)
        self.report({'INFO'}, f"自动识别完成: {total} 个骨骼角色已填充")
        return {'FINISHED'}
