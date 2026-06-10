"""Step 2 — 补全缺失骨骼: build the missing standard MMD bones + split inserted ones.

Pure skeleton construction: control bones (全ての親/センター/グルーブ/腰), the upper/lower
body, arms, legs, toe-EX, 腰キャンセル, finger metacarpals (指０), and the inserted
上半身1 / 首1. Weight work is delegated to weights/chain.py (the inserted bones and the
armpit smoothing). Additional-transform grants (incl. 腰キャンセル) are set later by the
unified grants step — here 腰キャンセル is only created and hidden.

Generalisation contract: NEVER KeyError on a missing bone. Anything an
arbitrary XPS rig may lack is either synthesised from geometry (首/頭 from each
other, 肩 from 腕+chest, 足先EX from the foot) or that body part is skipped
per-side with a console note — one missing arm must not abort the pipeline.
Synthesised bones carry no weights (the skin keeps riding the bones that had
the weights all along), they only complete the standard MMD hierarchy.
"""

import bpy
from mathutils import Vector

from .. import bone_utils
from .weights.chain import split_chain_weights


class OBJECT_OT_complete_missing_bones(bpy.types.Operator):
    """补充缺失的 MMD 格式骨骼"""
    bl_idname = "object.complete_missing_bones"
    bl_label = "Complete Missing Bones"

    def _connect_finger_bones(self, edit_bones):
        finger_chains = [
            ["左親指０", "左親指１", "左親指２"], ["左人指１", "左人指２", "左人指３"],
            ["左中指１", "左中指２", "左中指３"], ["左薬指１", "左薬指２", "左薬指３"],
            ["左小指１", "左小指２", "左小指３"], ["右親指０", "右親指１", "右親指２"],
            ["右人指１", "右人指２", "右人指３"], ["右中指１", "右中指２", "右中指３"],
            ["右薬指１", "右薬指２", "右薬指３"], ["右小指１", "右小指２", "右小指３"],
        ]
        for chain in finger_chains:
            if all(b in edit_bones for b in chain):
                for i in range(len(chain) - 1):
                    edit_bones[chain[i]].tail = edit_bones[chain[i + 1]].head

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "没有选择骨架")
            return {'CANCELLED'}
        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = obj.data.edit_bones
        notes = []

        def _head(name):
            b = edit_bones.get(name)
            return b.head.copy() if b else None

        upper_body_bone = edit_bones.get("上半身")
        if not upper_body_bone:
            self.report({'ERROR'}, "上半身骨骼不存在")
            return {'CANCELLED'}

        for name in ("左足", "右足"):
            b = edit_bones.get(name)
            if b:
                b.use_connect = False
                b.parent = None
        for name in ("上半身", "下半身"):
            b = edit_bones.get(name)
            if b and b.parent:
                b.use_connect = False
                b.parent = None
        upper_body_head = upper_body_bone.head.copy()
        upper_body_tail = upper_body_bone.tail.copy()

        bone_length = bone_utils.calculate_bone_length(edit_bones)

        upper_chain_bones = [f"上半身{i}" for i in range(2, 6) if edit_bones.get(f"上半身{i}")]
        last_upper_body = upper_chain_bones[-1] if upper_chain_bones else "上半身"
        chest_head = _head(last_upper_body) or upper_body_head

        # --- 首/頭: synthesise the missing one from the other -----------------
        neck_head = _head("首")
        head_head = _head("頭")
        if head_head is None and neck_head is not None:
            head_head = neck_head + Vector((0, 0, bone_length * 0.6))
            notes.append("合成 頭 (首上方)")
        if neck_head is None and head_head is not None:
            neck_head = Vector((0, head_head.y, head_head.z - bone_length * 0.45))
            notes.append("合成 首 (頭下方)")

        has_left_leg = bool(edit_bones.get("左足") and edit_bones.get("左ひざ") and edit_bones.get("左足首"))
        has_right_leg = bool(edit_bones.get("右足") and edit_bones.get("右ひざ") and edit_bones.get("右足首"))
        left_leg_parent = "腰キャンセル.L" if has_left_leg else "下半身"
        right_leg_parent = "腰キャンセル.R" if has_right_leg else "下半身"

        bp = {
            "全ての親": {"head": Vector((0, 0, 0)), "tail": Vector((0, 0, bone_length)), "parent": None, "use_deform": False, "use_connect": False},
            "センター": {"head": Vector((0, 0, bone_length * 2)), "tail": Vector((0, 0, bone_length * 1.1)), "parent": "全ての親", "use_deform": False, "use_connect": False},
            "グルーブ": {"head": Vector((0, 0, bone_length * 3.2)), "tail": Vector((0, 0, bone_length * 4)), "parent": "センター", "use_deform": False, "use_connect": False},
            "腰": {"head": Vector((0, upper_body_head.y + bone_length * 0.5, upper_body_head.z - bone_length * 0.5)), "tail": Vector((0, upper_body_head.y, upper_body_head.z)), "parent": "グルーブ", "use_deform": False, "use_connect": False},
            "上半身": {"head": Vector((0, upper_body_head.y, upper_body_head.z)), "tail": Vector((0, upper_body_tail.y, upper_body_head.z + bone_length)), "parent": "腰", "use_connect": False},
            "下半身": {"head": Vector((0, upper_body_head.y, upper_body_head.z)), "tail": Vector((0, upper_body_head.y, upper_body_head.z - bone_length)), "parent": "腰", "use_connect": False},
        }

        if neck_head is not None and head_head is not None:
            bp["首"] = {"head": neck_head, "tail": head_head, "parent": last_upper_body, "use_connect": False}
            bp["頭"] = {"head": head_head, "tail": Vector((0, head_head.y, head_head.z + bone_length * 0.25)), "parent": "首", "use_connect": False}
        else:
            notes.append("首/頭 均缺失 — 跳过颈部")

        # --- arms per side (one missing arm must not kill the other) ---------
        for s in ("左", "右"):
            arm_h = _head(f"{s}腕")
            el_h = _head(f"{s}ひじ")
            wr_h = _head(f"{s}手首")
            if not (arm_h and el_h and wr_h):
                notes.append(f"{s}腕链不完整 — 跳过该侧手臂")
                continue
            sh_h = _head(f"{s}肩")
            if sh_h is None:
                # synthesise the clavicle: from a quarter way out of the chest
                # toward the upper-arm head, at the arm's height (weightless).
                sh_h = Vector((arm_h.x * 0.3, arm_h.y, arm_h.z))
                notes.append(f"合成 {s}肩 (无锁骨骨架)")
            mid1_h = _head(f"{s}中指１")
            bp[f"{s}肩"] = {"head": sh_h, "tail": arm_h, "parent": last_upper_body, "use_connect": False}
            bp[f"{s}腕"] = {"head": arm_h, "tail": el_h, "parent": f"{s}肩", "use_connect": True}
            bp[f"{s}ひじ"] = {"head": el_h, "tail": wr_h, "parent": f"{s}腕", "use_connect": True}
            bp[f"{s}手首"] = {"head": wr_h, "tail": mid1_h if mid1_h is not None else wr_h + (wr_h - el_h) * 0.5, "parent": f"{s}ひじ", "use_connect": False}

        # --- legs per side ----------------------------------------------------
        # 腰キャンセル: cancels 腰 rotation for the legs (grant set later by grants step).
        for s, has_leg, leg_parent in (("左", has_left_leg, left_leg_parent),
                                       ("右", has_right_leg, right_leg_parent)):
            if not has_leg:
                if edit_bones.get(f"{s}足"):
                    notes.append(f"{s}腿链不完整 — 跳过该侧腿")
                continue
            foot_h = _head(f"{s}足")
            knee_h = _head(f"{s}ひざ")
            ankle_h = _head(f"{s}足首")
            bp[f"腰キャンセル.{ 'L' if s == '左' else 'R' }"] = {
                "head": foot_h, "tail": foot_h + Vector((0, 0, bone_length * 0.5)),
                "parent": "下半身", "use_connect": False, "use_deform": False}
            bp[f"{s}足"] = {"head": foot_h, "tail": knee_h, "parent": leg_parent, "use_connect": False}
            bp[f"{s}ひざ"] = {"head": knee_h, "tail": ankle_h, "parent": f"{s}足", "use_connect": False}
            bp[f"{s}足首"] = {"head": ankle_h, "tail": Vector((ankle_h.x, ankle_h.y - bone_length * 0.3, 0)), "parent": f"{s}ひざ", "use_connect": False}
            # 足先EX: keep the (renamed) toe bone's head; otherwise synthesise
            # at ground level in front of the ankle. The importer-made ankle
            # tail is NOT trusted (XPS bones have no tails — XNALaraMesh
            # invents them, and with no toe child the tail is junk).
            toe_eb = edit_bones.get(f"{s}足先EX")
            if toe_eb:
                toe_h = toe_eb.head.copy()
            else:
                toe_h = Vector((ankle_h.x, ankle_h.y - bone_length * 0.55, 0))
                notes.append(f"合成 {s}足先EX (无趾骨)")
            bp[f"{s}足先EX"] = {"head": toe_h, "tail": toe_h + Vector((0, -bone_length * 0.5, 0)), "parent": f"{s}足首", "use_connect": False}
            bp[f"{s}足首"]["tail"] = toe_h

        # 上半身链 (上半身2..5): tail → next segment, parent → previous.
        if upper_chain_bones:
            for idx, bone_name in enumerate(upper_chain_bones):
                next_name = upper_chain_bones[idx + 1] if idx + 1 < len(upper_chain_bones) else None
                if next_name:
                    tail_ref_head = _head(next_name)
                elif neck_head is not None:
                    tail_ref_head = neck_head
                else:
                    tail_ref_head = _head(bone_name) + Vector((0, 0, bone_length))
                bp[bone_name] = {
                    "head": Vector((0, _head(bone_name).y, _head(bone_name).z)),
                    "tail": Vector((0, tail_ref_head.y, tail_ref_head.z)),
                    "parent": upper_chain_bones[idx - 1] if idx > 0 else "上半身",
                    "use_connect": False,
                }

        # 上半身1 auto-insert between 上半身 and the first upper-chain segment.
        first_upper_chain = upper_chain_bones[0] if upper_chain_bones else None
        upper1_just_created = False
        if first_upper_chain and not edit_bones.get("上半身1"):
            ub_head = bp["上半身"]["head"].copy()
            ub2_head = bp[first_upper_chain]["head"].copy()
            mid = (ub_head + ub2_head) * 0.5
            if (ub2_head - ub_head).length > bone_length * 0.2:
                bp["上半身"]["tail"] = mid.copy()
                bp["上半身1"] = {"head": mid.copy(), "tail": ub2_head.copy(), "parent": "上半身", "use_connect": False, "use_deform": True}
                bp[first_upper_chain]["parent"] = "上半身1"
                upper1_just_created = True

        # 首1 auto-insert between 首 and 頭.
        neck1_just_created = False
        if "首" in bp and "頭" in bp and not edit_bones.get("首1"):
            nh = bp["首"]["head"].copy()
            hh = bp["頭"]["head"].copy()
            neck_mid = (nh + hh) * 0.5
            if (hh - nh).length > bone_length * 0.2:
                bp["首"]["tail"] = neck_mid.copy()
                bp["首1"] = {"head": neck_mid.copy(), "tail": hh.copy(), "parent": "首", "use_connect": False, "use_deform": True}
                bp["頭"]["parent"] = "首1"
                neck1_just_created = True

        # finger metacarpals (人指０/中指０/薬指０/小指０): pass-through, no weight split here.
        finger_root_defs = [("人指０", "人指１"), ("中指０", "中指１"), ("薬指０", "薬指１"), ("小指０", "小指１")]
        for side in ("左", "右"):
            wrist = edit_bones.get(f"{side}手首")
            if not wrist:
                continue
            for root_base, first_base in finger_root_defs:
                root_name = f"{side}{root_base}"
                first_name = f"{side}{first_base}"
                if edit_bones.get(root_name) or not edit_bones.get(first_name):
                    continue
                first_eb = edit_bones[first_name]
                bp[root_name] = {"head": (wrist.head + first_eb.head) * 0.5, "tail": first_eb.head.copy(), "parent": f"{side}手首", "use_connect": False, "use_deform": True}
                bp[first_name] = {"head": first_eb.head.copy(), "tail": first_eb.tail.copy(), "parent": root_name, "use_connect": False}

        # create/update all bones
        for bone_name, properties in bp.items():
            bone_utils.create_or_update_bone(edit_bones, bone_name, properties["head"], properties["tail"],
                                             properties.get("use_connect", False), properties["parent"],
                                             properties.get("use_deform", True))

        # second pass: fix parents (a child may have been created before its parent)
        for bone_name, properties in bp.items():
            parent_name = properties.get("parent")
            if parent_name and bone_name in edit_bones:
                parent_bone = edit_bones.get(parent_name)
                if parent_bone and edit_bones[bone_name].parent != parent_bone:
                    edit_bones[bone_name].parent = parent_bone

        # leftover pelvis helpers (any naming) hang under 下半身
        lower_body = edit_bones.get("下半身")
        if lower_body:
            for b in list(edit_bones):
                if b.name != "下半身" and "pelvis" in b.name.lower() and b.parent is None:
                    b.parent = lower_body
            pelvis_bone = edit_bones.get("unused bip001 pelvis")
            if pelvis_bone:
                pelvis_bone.parent = lower_body

        bone_utils.set_roll_values(edit_bones, bone_utils.DEFAULT_ROLL_VALUES)
        self._connect_finger_bones(edit_bones)

        # weight splits for the inserted bones (OBJECT mode for vertex-group edits)
        if upper1_just_created and first_upper_chain:
            bpy.ops.object.mode_set(mode='OBJECT')
            try:
                split_chain_weights(obj, "上半身", "上半身1", "上半身", first_upper_chain)
            except Exception as e:
                print(f"[complete] 上半身1 权重分割失败: {e}")
            bpy.ops.object.mode_set(mode='EDIT')
        if neck1_just_created:
            bpy.ops.object.mode_set(mode='OBJECT')
            try:
                split_chain_weights(obj, "首", "首1", "首", "頭")
            except Exception as e:
                print(f"[complete] 首1 权重分割失败: {e}")
            bpy.ops.object.mode_set(mode='EDIT')

        # armpit smoothing: 肩→腕 additive (src_keep_floor=1.0, don't thin 肩)
        bpy.ops.object.mode_set(mode='OBJECT')
        for side_jp in ("左", "右"):
            shoulder, arm_bone = f"{side_jp}肩", f"{side_jp}腕"
            if obj.data.bones.get(shoulder) and obj.data.bones.get(arm_bone):
                try:
                    split_chain_weights(obj, shoulder, arm_bone, shoulder, arm_bone, src_keep_floor=1.0)
                except Exception as e:
                    print(f"[complete] 腋窝平滑 {shoulder} 失败: {e}")

        # hide 腰キャンセル (grant applied later by the unified grants step)
        for side in (".L", ".R"):
            bone = obj.data.bones.get(f"腰キャンセル{side}")
            if bone:
                bone.hide = True

        if notes:
            print("[complete] 降级/合成: " + "; ".join(notes))

        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}
