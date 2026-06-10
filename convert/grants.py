"""Unified MMD additional-transform (付与) table.

Every semi-standard bone that inherits a fraction of another bone's rotation is
declared here in ONE place, and applied as `mmd_bone.additional_transform`. The old
code set these in four different spots (a dedicated operator, the twist operator's
own grant pass, the leg-D/肩P hand-wired constraints, and complete's 腰キャンセル) —
often redundantly. Consolidating them is the core of the req-3 redesign:

  set grants here  →  call mmd_tools.apply_additional_transform once  →  mmd_tools
  builds every relay itself (a direct local constraint when the granted bone is
  aligned with its source, e.g. 足D/肩C; a _dummy_/_shadow_ world-space relay when it
  is deliberately misaligned for display, e.g. the up-pointing twist subs).

So no module hand-builds _dummy_/_shadow_ bones or TRANSFORM/COPY_TRANSFORMS
constraints anymore — mmd_tools owns that, uniformly (req 2 + req 3).
"""

import bpy


def grant_specs():
    """Return (bone_name, source_name, influence, is_tip) for all 付与 relations."""
    specs = []
    for s in ("左", "右"):
        # shoulder cancel: 肩C undoes 肩P (rate -1)
        specs.append((f"{s}肩C", f"{s}肩P", -1.0, False))
        # twist subs follow the main twist at 0.25 / 0.50 / 0.75
        for i, infl in ((1, 0.25), (2, 0.50), (3, 0.75)):
            specs.append((f"{s}腕捩{i}", f"{s}腕捩", infl, False))
            specs.append((f"{s}手捩{i}", f"{s}手捩", infl, False))
        # leg deform bones follow their FK counterpart fully (rate 1)
        specs.append((f"{s}足D", f"{s}足", 1.0, False))
        specs.append((f"{s}ひざD", f"{s}ひざ", 1.0, False))
        specs.append((f"{s}足首D", f"{s}足首", 1.0, False))
    # waist cancel: undoes 腰 for the legs (rate -1, tip bone)
    for suffix in (".L", ".R"):
        specs.append((f"腰キャンセル{suffix}", "腰", -1.0, True))
    return specs


def apply_grants(arm):
    """Set mmd_bone additional-transform for every spec whose bones exist. Returns count."""
    n = 0
    pose_bones = arm.pose.bones
    for name, src, infl, is_tip in grant_specs():
        pb = pose_bones.get(name)
        if not pb or not pose_bones.get(src):
            continue
        mb = getattr(pb, "mmd_bone", None)
        if mb is None:
            continue
        try:
            mb.has_additional_rotation = True
            mb.has_additional_location = False
            mb.additional_transform_bone = src
            mb.additional_transform_influence = infl
            if is_tip:
                mb.is_tip = True
            n += 1
        except Exception as e:
            print(f"[grants] {name} ← {src} 设置失败: {e}")
    return n


class OBJECT_OT_setup_mmd_grants(bpy.types.Operator):
    """设置 MMD 标准付与(肩C/腕捩/手捩/D骨/腰キャンセル)，让导出 PMX 带付与标志"""
    bl_idname = "object.setup_mmd_grants"
    bl_label = "设置标准付与(付与)"
    bl_description = "为捩骨/D骨/肩C/腰キャンセル 设置 mmd_bone 付与关系，导出 PMX 时生效"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type != 'ARMATURE':
            obj = next((o for o in bpy.data.objects
                        if o.type == 'ARMATURE' and 'backup' not in o.name.lower()), None)
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未找到骨架")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        n = apply_grants(obj)
        self.report({'INFO'}, f"已设置 {n} 个标准付与关系")
        return {'FINISHED'}
