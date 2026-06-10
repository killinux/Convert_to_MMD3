"""SYNTHESIS exception: build palm weights XPS never had.

This is the only place that genuinely *synthesises* weight rather than reusing or
re-grading XPS weight: XPS has no metacarpal vertex groups at all, so the whole
palm rides rigidly on 手首. Two conserving, position-driven redistributions
reproduce the target PMX hand:

  1. de-bleed 親指０ — XPS binds the thumb metacarpal too wide; ~29–41% of its weight
     sits behind the thumb base on the inner wrist (target ~1%). Ramp it back to 手首.
  2. palm → 指０ — hand the palm region of 手首 to the four metacarpals 人指０/中指０/
     薬指０/小指０ by hand-depth, blending laterally between adjacent fingers.

Both conserve each vertex's total weight. Runs after twist (so 手首 has already
reclaimed its forearm side). Constants calibrated to the target PMX, preserved.
"""

import bpy

from .common import skinned_meshes, vgroup_weight, ensure_vgroup, find_main_armature

# Palm redistribution along 手首→中指 hand-depth d (0=wrist joint, 1=middle-finger root):
# d<LO fully kept on 手首, d>HI fully to metacarpals, linear between. Laterally blended
# across fingers by inverse-power of point-to-(指０→指１)-segment distance.
PALM_D_LO = 0.10
PALM_D_HI = 0.80
PALM_LATERAL_POW = 2
PALM_FINGERS = ("人指", "中指", "薬指", "小指")

# Thumb de-bleed along the thumb axis u (0=親指０ head, 1=親指１): u<U_HI ramps to 手首,
# u<=U_LO fully moved. Calibrated to the target (親指０ only ~1% behind the thumb base).
THUMB_U_HI = -0.1
THUMB_U_LO = -0.5

# The de-bled weight is split between 手首 (wrist) and 手捩 (forearm twist) by the vertex's
# position t along the forearm axis (ひじ head=0 → 手首 head=1.0): t<=LO → all 手捩,
# t>=HI → all 手首, linear between. XPS can't encode this split (no twist bone), so it's
# derived from position — same wrist-centred band as twist.py's RECLAIM. Conserving.
DEBLEED_T_LO = 0.90
DEBLEED_T_HI = 1.10


def _pt_seg_dist(p, a, b):
    ab = b - a
    L2 = ab.length_squared
    if L2 < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / L2))
    return (p - (a + ab * t)).length


def debleed_thumb_to_wrist(obj):
    """De-bleed 親指０ off the inner wrist, splitting it 手首/手捩 by position (conserving).

    The thumb-base bleed straddles the wrist joint (t≈1.0 on the forearm axis), so each
    vertex is shared between the wrist (手首) and the forearm twist (手捩) by a wrist-centred
    position ramp (DEBLEED_T_LO/HI) instead of dumping all of it on 手首: a vertex on the
    forearm side follows the twist, one on the hand side follows the wrist. Falls back to
    all-手首 when 手捩 is absent.
    """
    meshes = skinned_meshes(obj)
    mw = obj.matrix_world
    span = max(THUMB_U_HI - THUMB_U_LO, 1e-6)
    tspan = max(DEBLEED_T_HI - DEBLEED_T_LO, 1e-6)
    total = 0
    for side in ("左", "右"):
        b0 = obj.data.bones.get(f"{side}親指０")
        b1 = obj.data.bones.get(f"{side}親指１")
        elbow = obj.data.bones.get(f"{side}ひじ")
        wrist = obj.data.bones.get(f"{side}手首")
        if not b0 or not b1 or not wrist or not elbow:
            continue
        A = mw @ b0.head_local
        axis = (mw @ b1.head_local) - A
        Lt = axis.length
        if Lt < 1e-6:
            continue
        axn = axis / Lt
        # forearm axis (ひじ head=0 → 手首 head=1.0) drives the wrist/twist split
        F0 = mw @ elbow.head_local
        fvec = (mw @ wrist.head_local) - F0
        Lf = fvec.length
        if Lf < 1e-6:
            continue
        fn = fvec / Lf
        has_twist = obj.data.bones.get(f"{side}手捩") is not None
        for m in meshes:
            t0 = m.vertex_groups.get(f"{side}親指０")
            if not t0:
                continue
            wf = ensure_vgroup(m, f"{side}手首")
            wft = ensure_vgroup(m, f"{side}手捩") if has_twist else None
            plans = []
            for v in m.data.vertices:
                w = vgroup_weight(v, t0.index)
                if w <= 1e-6:
                    continue
                vco = m.matrix_world @ v.co
                u = (vco - A).dot(axn) / Lt
                if u >= THUMB_U_HI:
                    continue
                moved = w * min(1.0, (THUMB_U_HI - u) / span)
                if moved <= 1e-6:
                    continue
                # split by forearm position: t<=LO → all 手捩, t>=HI → all 手首
                t = (vco - F0).dot(fn) / Lf
                f_twist = max(0.0, min(1.0, (DEBLEED_T_HI - t) / tspan)) if wft else 0.0
                plans.append((v.index, w - moved, moved * (1.0 - f_twist), moved * f_twist))
            for vidx, neww, to_wrist, to_twist in plans:
                if neww > 1e-6:
                    t0.add([vidx], neww, 'REPLACE')
                else:
                    t0.remove([vidx])
                if to_wrist > 1e-6:
                    wf.add([vidx], to_wrist, 'ADD')
                if wft and to_twist > 1e-6:
                    wft.add([vidx], to_twist, 'ADD')
                total += 1
    return total


def redistribute_palm_to_metacarpals(obj):
    """Hand the palm region of 手首 to the four 指０ metacarpals by position (conserving)."""
    meshes = skinned_meshes(obj)
    mw = obj.matrix_world
    total = 0
    for side in ("左", "右"):
        bw = obj.data.bones.get(f"{side}手首")
        bmid = obj.data.bones.get(f"{side}中指１")
        cols = [(f, obj.data.bones.get(f"{side}{f}０")) for f in PALM_FINGERS]
        cols = [(f, b) for f, b in cols if b]
        if not bw or not bmid or len(cols) < 2:
            continue
        W = mw @ bw.head_local
        H = (mw @ bmid.head_local) - W
        Hlen = H.length
        if Hlen < 1e-6:
            continue
        Hn = H / Hlen
        rays = [(f, mw @ b.head_local, mw @ obj.data.bones[f"{side}{f}１"].head_local)
                for f, b in cols if obj.data.bones.get(f"{side}{f}１")]
        if len(rays) < 2:
            continue
        for m in meshes:
            wvg = m.vertex_groups.get(f"{side}手首")
            if not wvg:
                continue
            mvg = {f: ensure_vgroup(m, f"{side}{f}０") for f, _, _ in rays}
            plans = []
            for v in m.data.vertices:
                w = vgroup_weight(v, wvg.index)
                if w <= 1e-6:
                    continue
                vp = m.matrix_world @ v.co
                d = (vp - W).dot(Hn) / Hlen
                if d <= PALM_D_LO:
                    continue
                frac = min(1.0, (d - PALM_D_LO) / (PALM_D_HI - PALM_D_LO))
                if frac <= 1e-4:
                    continue
                moved = w * frac
                wt = {}
                sw = 0.0
                for f, a, b in rays:
                    ww = 1.0 / (_pt_seg_dist(vp, a, b) ** PALM_LATERAL_POW + 1e-9)
                    wt[f] = ww
                    sw += ww
                plans.append((v.index, w - moved, {f: moved * wt[f] / sw for f in wt}))
            for vidx, new_w, add in plans:
                if new_w > 1e-6:
                    wvg.add([vidx], new_w, 'REPLACE')
                else:
                    wvg.remove([vidx])
                for f, aw in add.items():
                    if aw > 1e-6:
                        mvg[f].add([vidx], aw, 'ADD')
                total += 1
    return total


class OBJECT_OT_fix_palm_weights(bpy.types.Operator):
    """手部权重修正：先把 親指０ 渗到手腕的权重还给 手首，再把 手首 手掌段分给 指０ 掌骨。"""
    bl_idname = "object.fix_palm_weights"
    bl_label = "掌部权重分给掌骨"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            obj = find_main_armature()
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未找到骨架")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            nt = debleed_thumb_to_wrist(obj)
            n = redistribute_palm_to_metacarpals(obj)
        except Exception as e:
            self.report({'ERROR'}, f"手部权重修正失败: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"手部权重修正: 拇指渗出 {nt} 顶点→手首, 掌部 {n} 顶点→掌骨")
        return {'FINISHED'}
