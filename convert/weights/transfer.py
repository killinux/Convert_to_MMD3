"""REUSE path: move XPS helper/unused-bone weights onto valid MMD deform bones.

This is the *default* weight policy (req 1: "reuse XPS weights first"). It never
synthesises weight — it only re-homes weight that XPS already painted onto bones
that MMD doesn't keep, onto the right deform bone so the existing skin is
preserved. Three position-driven routes, first match wins per helper:

  deltoid  — shoulder-cap helpers (XPS xtra07/xtra07pp and friends): split
             across 肩 (top) / 腕 (lower) by a ramp along the arm axis, like
             the target PMX hand-off.
  segment  — helpers whose weight centroid lives inside an arm/palm segment
             tube (UE upperarm_twist_01_l, Valve Ulna/Wrist, Daz lShldrTwist,
             XPS foretwist — REGARDLESS of name): the whole group folds into
             the segment's pool bone (腕/ひじ/手首). The later twist split
             (step 7) re-grades the pool by vertex position, so folded twist
             weight ends up on 腕捩/手捩 exactly like native XPS arm weight.
             Without this, ports keeping their engine twist bones stay
             candy-wrapped on those vertices (XPS has no constraints — the
             helpers are dead bones after conversion).
  nearest  — everything else consumed (spine helpers, misc 'unused'): each
             vertex goes to the nearest valid deform bone (legacy behaviour).

Physics strands (skirt/hair/tail/breast — classifier 'preserve') and face/hand
detail bones are never consumed. The harder *synthesis* splits (twist τ, palm,
chain) live in their own modules.
"""

import bpy

from .common import skinned_meshes
from .fold import build_arm_segments, plan_segment_folds
from ...skeleton_identifier import identify_skeleton
from ...helper_classifier import classify_helpers
from ...skeleton_identifier import clear_cache


# Deltoid (shoulder-cap) routing ramp along the 腕→ひじ axis (t=0 arm head/shoulder
# joint, 1=elbow). Top of the cap (t<=LO) → 肩; lower (t>=HI) → 腕 base; linear
# between. HI=0.25 is remote-calibrated so the 肩↔腕 hand-off sits at ~t0.4 along
# 肩→ひじ, matching the target PMX (肩≈腕≈8% at t0.4, 肩→0 by t0.5). The lower part
# lands on the 腕 base (low t) and barely twists (twist TAU_LO=0.20) → no candy-wrap.
DELTOID_SH_T_LO = 0.0
DELTOID_SH_T_HI = 0.25


def deltoid_shoulder_fraction(t):
    """Fraction of a deltoid vertex (at axis param t) that goes to 肩; rest to 腕."""
    if t <= DELTOID_SH_T_LO:
        return 1.0
    if t >= DELTOID_SH_T_HI:
        return 0.0
    return (DELTOID_SH_T_HI - t) / (DELTOID_SH_T_HI - DELTOID_SH_T_LO)


def _weight_centroids(meshes, cand_names):
    """World-space weighted centroid of every candidate bone's vertex weights."""
    acc = {}  # name -> [sum(w*pos) Vector, sum(w)]
    for m in meshes:
        idx2name = {}
        for name in cand_names:
            vg = m.vertex_groups.get(name)
            if vg:
                idx2name[vg.index] = name
        if not idx2name:
            continue
        mmw = m.matrix_world
        for v in m.data.vertices:
            wp = None
            for g in v.groups:
                nm = idx2name.get(g.group)
                if nm and g.weight > 0.001:
                    if wp is None:
                        wp = mmw @ v.co
                    s = acc.get(nm)
                    if s is None:
                        acc[nm] = [wp * g.weight, g.weight]
                    else:
                        s[0] += wp * g.weight
                        s[1] += g.weight
    return {nm: sw / w for nm, (sw, w) in acc.items() if w > 0}


def _resolve_arm_names(obj, smap):
    """{MMD名: 当前骨名} for the fold segments — works before AND after rename.

    Resolution order: the identifier's topology mapping (pre-rename names),
    falling back to the MMD name when the bone already carries it.
    """
    role_for = {
        "左肩": "left_shoulder_bone", "右肩": "right_shoulder_bone",
        "左腕": "left_upper_arm_bone", "右腕": "right_upper_arm_bone",
        "左ひじ": "left_lower_arm_bone", "右ひじ": "right_lower_arm_bone",
        "左手首": "left_hand_bone", "右手首": "right_hand_bone",
        "左中指１": "left_middle_1", "右中指１": "right_middle_1",
    }
    out = {}
    for mmd_name, role in role_for.items():
        cand = smap.get(role) if smap else None
        if cand and obj.data.bones.get(cand):
            out[mmd_name] = cand
        elif obj.data.bones.get(mmd_name):
            out[mmd_name] = mmd_name
    return out


def _detect_arm_deltoid(obj, centroids, name_map):
    """Identify shoulder-cap helpers among `centroids` and return
    {bone_name: (肩名, 腕名, origin, axis, L2)} so transfer can split them by
    position along the 腕→ひじ axis."""
    mw = obj.matrix_world
    sides = []  # (origin, axis, L2, armlen, shoulder_name, arm_name)
    for jp in ("左", "右"):
        arm = obj.data.bones.get(name_map.get(f"{jp}腕", ""))
        el = obj.data.bones.get(name_map.get(f"{jp}ひじ", ""))
        sh = obj.data.bones.get(name_map.get(f"{jp}肩", ""))
        if arm and el and sh:
            o = mw @ arm.head_local
            ax = (mw @ el.head_local) - o
            L2 = ax.length_squared
            if L2 > 1e-9:
                sides.append((o, ax, L2, L2 ** 0.5, sh.name, arm.name))
    if not sides:
        return {}
    dest = {}
    for nm, c in centroids.items():
        best = None
        for o, ax, L2, alen, shname, armname in sides:
            t = (c - o).dot(ax) / L2
            proj = o + ax * max(0.0, min(1.0, t))
            lat = (c - proj).length
            if best is None or lat < best[0]:
                best = (lat, shname, t, alen, armname, o, ax, L2)
        lat, shname, t, alen, armname, o, ax, L2 = best
        # Deltoid: centroid at 0.05<=t<=0.55 (proximal-to-mid upper arm) and
        # laterally within half an upper-arm length (hugging the arm). Excludes
        # head/neck/root behind the shoulder (t<0), elbow-side twist (t>0.55),
        # and laterally-distant chest/control bones.
        if 0.05 <= t <= 0.55 and lat < 0.5 * alen:
            dest[nm] = (shname, armname, o, ax, L2)
    return dest


def _rehome_leg_helper_bleed(obj, mesh_objects, smap, cls):
    """Fix cross-joint weight bleed on PRESERVED leg helpers (req: reuse, but on
    the bone that actually drives the flesh).

    A leftover XPS helper that rides the thigh (e.g. `unused muscle strand070`,
    parent 左足) but paints lower-leg vertices drags those calf vertices with the
    THIGH on a knee bend — they lag while the rest of the calf swings, denting
    the calf belly. The classifier keeps such helpers ('preserve', via the thigh
    rule that protects legit mid-thigh shapers like inase's xtra04), so the
    normal nearest/​fold routes never touch them.

    This pass moves ONLY the bled vertices — those lying in a different leg
    segment than the helper's own leg anchor — onto the leg deform bone whose
    tube they actually sit in, per vertex, weight-conserving. A helper whose
    vertices all stay in its own segment (a real thigh shaper) is left untouched.
    Targets the base bone (左足/左ひざ/左足首); step 6 renames those groups to the
    D bones, so the rehomed weight merges seamlessly with the surrounding skin.

    Scope guards (each must hold): name starts 'unused' (XPS dead helpers only —
    structurally spares native-named shapers like xtra04, matching the existing
    nearest-route policy), classifier == 'preserve', use_deform, and a leg-bone
    ancestor. Geometry decides the rest: only verts inside the leg tube and
    across a joint move. Heads-only segments (tail is XNALaraMesh-synthesised).
    """
    if not smap or not cls:
        return 0
    mw = obj.matrix_world
    bones = obj.data.bones
    # Resolve per-side leg chain (thigh→shin→ankle). Post-rename the bones carry
    # MMD names; smap role values may still be the pre-rename names — try the
    # role first, fall back to the MMD name.
    role_names = {
        '左': [('left_thigh_bone', '左足'), ('left_calf_bone', '左ひざ'),
               ('left_ankle_bone', '左足首')],
        '右': [('right_thigh_bone', '右足'), ('right_calf_bone', '右ひざ'),
               ('right_ankle_bone', '右足首')],
    }
    leg_set = set()
    side_segs = {}  # side -> [(deform_bone_name, p0, p1, seg_len)]
    for side, roles in role_names.items():
        seq = []
        for role, mmd_name in roles:
            cand = smap.get(role)
            b = (bones.get(cand) if cand else None) or bones.get(mmd_name)
            if b:
                seq.append(b)
                leg_set.add(b.name)
        if len(seq) < 2:
            continue
        heads = [mw @ b.head_local for b in seq]
        segs = []
        for i in range(len(seq) - 1):
            p0, p1 = heads[i], heads[i + 1]
            L = (p1 - p0).length
            if L > 1e-6:
                segs.append((seq[i].name, p0, p1, L))  # bone drives flesh below its head
        if segs:
            side_segs[side] = segs
    if not side_segs:
        return 0

    def _leg_anchor(bone):
        cur = bone.parent
        while cur:
            if cur.name in leg_set:
                return cur.name
            cur = cur.parent
        return None

    def _vert_leg_bone(side, pos):
        """The leg deform bone whose tube `pos` sits in (nearest segment), or None."""
        best = None
        for name, p0, p1, L in side_segs[side]:
            seg = p1 - p0
            L2 = seg.length_squared
            if L2 < 1e-9:
                continue
            t = (pos - p0).dot(seg) / L2
            if not (-0.15 <= t <= 1.15):
                continue
            proj = p0 + max(0.0, min(1.0, t)) * seg
            perp = (pos - proj).length
            if perp < L * 0.30 and (best is None or perp < best[1]):
                best = (name, perp)
        return best[0] if best else None

    helpers = []
    for b in bones:
        if (b.name.startswith('unused') and b.use_deform
                and cls.get(b.name) == 'preserve' and b.name not in leg_set):
            anc = _leg_anchor(b)
            if anc:
                helpers.append((b.name, anc))
    if not helpers:
        return 0

    moved = 0
    for mesh in mesh_objects:
        for hname, anc in helpers:
            vg = mesh.vertex_groups.get(hname)
            if not vg:
                continue
            side = '左' if anc.startswith('左') else ('右' if anc.startswith('右') else None)
            if side not in side_segs:
                continue
            plans = []  # (vidx, weight, dest)
            for v in mesh.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.001:
                        dest = _vert_leg_bone(side, mw @ v.co)
                        if dest and dest != anc:
                            plans.append((v.index, g.weight, dest))
                        break
            for vidx, wt, dest in plans:
                tvg = mesh.vertex_groups.get(dest) or mesh.vertex_groups.new(name=dest)
                tvg.add([vidx], wt, 'ADD')
                vg.remove([vidx])
            moved += len(plans)
    return moved


class OBJECT_OT_transfer_unused_weights(bpy.types.Operator):
    """Move unused/control-bone weights onto the right valid deform bone."""
    bl_idname = "object.transfer_unused_weights"
    bl_label = "转移 unused 骨权重"
    bl_options = {'REGISTER', 'UNDO'}

    SKIP_PATTERNS = ('foretwist', 'muscle')
    CONTROL_BONES = ('全ての親', 'センター', 'グルーブ', '操作中心')
    STANDARD_MMD_BONES = frozenset((
        '上半身', '上半身1', '上半身2', '上半身3', '下半身', '首', '首1', '頭', '腰',
        '左肩', '右肩', '左腕', '右腕', '左ひじ', '右ひじ', '左手首', '右手首',
        '左足', '右足', '左ひざ', '右ひざ', '左足首', '右足首', '左足先EX', '右足先EX',
        '左目', '右目', '腰キャンセル.L', '腰キャンセル.R',
        '左人指０', '右人指０', '左中指０', '右中指０', '左薬指０', '右薬指０', '左小指０', '右小指０',
    ))

    def _auto_classify(self, armature):
        try:
            clear_cache()
            smap = identify_skeleton(armature.data)
            if sum(1 for v in smap.values() if v) < 5:
                return None, None
            return classify_helpers(armature.data, smap), smap
        except Exception:
            return None, None

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}

        mesh_objects = skinned_meshes(obj)
        if not mesh_objects:
            self.report({'ERROR'}, "未找到挂此 armature 的 mesh")
            return {'CANCELLED'}

        cls, smap = self._auto_classify(obj)

        if cls:
            # Foldable: every helper the classifier puts ON an arm segment —
            # name-agnostic, so game-port twist bones (UE/Valve/Daz/XPS
            # foretwist) are consumed too, not only 'unused*'-named ones.
            # This pipeline builds its OWN 腕捩/手捩; keeping weighted helper
            # twist bones would leave dead weights that never twist.
            fold_bones = [
                b for b in obj.data.bones
                if cls.get(b.name) == 'twist' and b.name not in self.STANDARD_MMD_BONES
            ]
            # Nearest re-home: spine merges + classic 'unused *' leftovers.
            nearest_bones = [
                b for b in obj.data.bones
                if (cls.get(b.name) == 'merge'
                    or (b.name.startswith('unused') and cls.get(b.name) == 'other'))
                and b.name not in self.STANDARD_MMD_BONES
            ]
            control_bones = [b for b in obj.data.bones if b.name in self.CONTROL_BONES]
            print("\n[Transfer unused] 使用 auto-classifier")
        else:
            fold_bones = []
            nearest_bones = [
                b for b in obj.data.bones
                if b.name.startswith('unused')
                and not any(p in b.name.lower() for p in self.SKIP_PATTERNS)
            ]
            control_bones = [b for b in obj.data.bones if b.name in self.CONTROL_BONES]
            print("\n[Transfer unused] 使用硬编码 patterns (fallback)")

        bones_to_transfer = fold_bones + nearest_bones + control_bones
        valid_deform_bones = [
            b for b in obj.data.bones
            if not b.name.startswith('unused')
            and not b.name.startswith('_shadow')
            and not b.name.startswith('_dummy')
            and b.use_deform
            and b not in bones_to_transfer
        ]
        if not valid_deform_bones:
            self.report({'ERROR'}, "无有效变形骨")
            return {'CANCELLED'}

        valid_heads = [(b, obj.matrix_world @ b.head_local) for b in valid_deform_bones]

        # one centroid pass feeds both the deltoid detector and the fold plan
        consumed_names = {b.name for b in fold_bones + nearest_bones}
        centroids = _weight_centroids(mesh_objects, consumed_names)
        name_map = _resolve_arm_names(obj, smap)

        deltoid_dest = _detect_arm_deltoid(obj, centroids, name_map)
        if deltoid_dest:
            print(f"[Transfer unused] 三角肌按位置分肩/腕: { {k: (v[0], v[1]) for k, v in deltoid_dest.items()} }")

        # segment folds for the remaining foldable helpers
        mw = obj.matrix_world

        def _head(mmd_name):
            b = obj.data.bones.get(name_map.get(mmd_name, ""))
            return (mw @ b.head_local) if b else None

        segments = build_arm_segments(_head)
        fold_centroids = {b.name: centroids[b.name] for b in fold_bones
                          if b.name in centroids and b.name not in deltoid_dest}
        segment_plan = plan_segment_folds(fold_centroids, segments)
        if segment_plan:
            print(f"[Transfer unused] 段上 helper 折叠: {segment_plan}")

        def _add(mesh, dest_name, vidx, wt):
            tvg = mesh.vertex_groups.get(dest_name) or mesh.vertex_groups.new(name=dest_name)
            tvg.add([vidx], wt, 'ADD')

        total_transferred = 0
        for mesh in mesh_objects:
            for ubone in bones_to_transfer:
                vg = mesh.vertex_groups.get(ubone.name)
                if not vg:
                    continue
                forced = deltoid_dest.get(ubone.name)
                pool = segment_plan.get(ubone.name)
                # Control bones end up weightless; their skin (if any) is re-homed
                # below to the NEAREST valid deform bone (position-driven), not
                # force-dumped on 下半身: a global root like 全ての親 (XPS root
                # ground) carries far-flung skin (e.g. hair) that must follow its
                # nearest body bone (頭); a pelvis bone's skin nearest-resolves to
                # 下半身 on its own.
                n = 0
                for v in mesh.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index and g.weight > 0.001:
                            if forced:
                                sh_name, arm_name, o, ax, L2 = forced
                                vert_pos = obj.matrix_world @ v.co
                                t = (vert_pos - o).dot(ax) / L2
                                sf = deltoid_shoulder_fraction(t)
                                if sf > 1e-6:
                                    _add(mesh, sh_name, v.index, g.weight * sf)
                                if sf < 1.0 - 1e-6:
                                    _add(mesh, arm_name, v.index, g.weight * (1.0 - sf))
                            elif pool:
                                _add(mesh, pool, v.index, g.weight)
                            else:
                                vert_pos = obj.matrix_world @ v.co
                                dest_name = min(valid_heads, key=lambda bh: (bh[1] - vert_pos).length)[0].name
                                _add(mesh, dest_name, v.index, g.weight)
                            n += 1
                            break
                if n > 0:
                    total_transferred += n
                if ubone.name in self.CONTROL_BONES:
                    vg.remove(list(range(len(mesh.data.vertices))))
                else:
                    mesh.vertex_groups.remove(vg)

        # pelvis helpers map straight to 下半身
        if cls:
            pelvis_bone_names = [b.name for b in obj.data.bones if cls.get(b.name) == 'pelvis']
        else:
            pelvis_bone_names = [
                b.name for b in obj.data.bones
                if b.name.startswith('unused') and 'pelvis' in b.name.lower()
            ]
        if pelvis_bone_names:
            for mesh in mesh_objects:
                lb_vg = mesh.vertex_groups.get('下半身') or mesh.vertex_groups.new(name='下半身')
                for pname in pelvis_bone_names:
                    vg = mesh.vertex_groups.get(pname)
                    if not vg:
                        continue
                    for v in mesh.data.vertices:
                        for g in v.groups:
                            if g.group == vg.index and g.weight > 0.001:
                                lb_vg.add([v.index], g.weight, 'ADD')
                                total_transferred += 1
                                break
                    mesh.vertex_groups.remove(vg)

        # Preserved leg helpers (kept for legit thigh shaping) can still bleed a
        # few vertices across the knee onto the wrong side — rehome just those.
        bled = _rehome_leg_helper_bleed(obj, mesh_objects, smap, cls)
        if bled:
            print(f"[Transfer unused] 腿 helper 跨膝渗漏回收: {bled} 顶点 → 正确腿骨")

        self.report({'INFO'}, f"转移 {total_transferred} 顶点权重")
        return {'FINISHED'}
