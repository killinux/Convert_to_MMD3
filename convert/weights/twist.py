"""SPLIT exception: distribute arm weight onto the twist bones along the bone axis.

XPS has no MMD twist bones, so 腕捩/手捩(+1/2/3) start empty. This splits the 腕/ひじ
weight onto them by a *twist-target* curve τ(t) so the twist is graded along the
forearm/upper-arm instead of rigid — conserving each vertex's total weight (scale
1.0, never thinned). The τ curve and the forearm reclaim are calibrated to the
target PMX; constants are preserved verbatim from the tuned implementation.

This is the twist *weight* policy only. The twist *bones* and their grants live in
semistandard.py; this module is called once the bones exist.
"""

from .common import skinned_meshes

# Twist gradient along the bone axis t∈[0,1] → twist ratio τ∈[0,1]. Shoulder side
# (t<TAU_LO) doesn't twist; wrist side (t>TAU_HI) fully twists; smooth between.
# Upper arm (腕): 0.20/0.80 — main 腕捩 lands at the elbow end t≈1.0, like the target.
# Kept faithful to the XPS source (no target-overriding redistribution): XPS binds the
# upper arm nearer the shoulder, so twist coverage (~24%) is below target (~51%); this
# is a source-mesh difference, accepted (full XPS reuse, no upper-arm override).
TAU_LO = 0.20
TAU_HI = 0.80
# Forearm (ひじ): main 手捩 lands at the wrist end t≈0.9; 手捩1/2/3/main peak at
# t≈0.34/0.53/0.71/0.90. TAU_LO_FOREARM=0.15 keeps the elbow-adjacent forearm pure ひじ
# so wrist-twist doesn't bleed onto the elbow ring — the target PMX's elbow ring is a
# clean 腕捩+ひじ BDEF2 (手捩1≈0.02). Was 0.05, which started 手捩 right at the elbow
# (~0.16 手捩1 bleed + spurious 3-bone elbow verts); 0.15 also nudges 手捩1's peak from
# t≈0.26 toward the ~0.3 target. TAU_HI 0.90 still grades distal weight across 手捩2/3.
TAU_LO_FOREARM = 0.15
TAU_HI_FOREARM = 0.90

# reclaim: fraction of a downstream bone's (手首) weight on this segment folded into
# the split pool, ramped along the segment axis t. t<=LO fully reclaimed (pure forearm),
# t>=HI not reclaimed (palm). Target calibration: 手首 enters the forearm at t≈0.9.
RECLAIM_LO = 0.90
RECLAIM_HI = 1.10

# main twist bone, then 1/2/3 subs; the source segment that is split.
TWIST_GROUPS = [
    ("左腕",  ["左腕捩", "左腕捩1", "左腕捩2", "左腕捩3"], None),
    ("左ひじ", ["左手捩", "左手捩1", "左手捩2", "左手捩3"], "左手首"),
    ("右腕",  ["右腕捩", "右腕捩1", "右腕捩2", "右腕捩3"], None),
    ("右ひじ", ["右手捩", "右手捩1", "右手捩2", "右手捩3"], "右手首"),
]


def split_twist_weights(obj):
    """Split 腕/ひじ weight onto the twist bones for both arms (weight-conserving)."""
    for mesh in skinned_meshes(obj):
        vgroups = mesh.vertex_groups
        for base_name, twist_names, reclaim_group in TWIST_GROUPS:
            if base_name.endswith("腕"):
                _split_segment(obj, mesh, vgroups, base_name, twist_names,
                               tau_lo=TAU_LO, tau_hi=TAU_HI)
            else:
                _split_segment(obj, mesh, vgroups, base_name, twist_names,
                               reclaim_group=reclaim_group,
                               tau_lo=TAU_LO_FOREARM, tau_hi=TAU_HI_FOREARM)


def _split_segment(obj, mesh, vgroups, base_name, twist_names,
                   reclaim_group=None, tau_lo=TAU_LO, tau_hi=TAU_HI):
    """Distribute base weight between adjacent twist levels by τ(t) (conserving).

    Twist levels: base=0, 捩1=0.25, 捩2=0.5, 捩3=0.75, main=1.0. A vertex's τ(t) lands
    between two levels and is shared between them → smooth overlap, continuous twist,
    weight conserved. reclaim_group (forearm only, 手首): XPS bound the distal forearm
    to the hand bone, so base(ひじ) covers only the elbow half; without reclaim the
    main 手捩/手捩3 get no weight. So 手首 weight on the forearm (t<RECLAIM_HI) is folded
    into the pool by ramp and equally debited from 手首 (palm t>=RECLAIM_HI untouched).
    """
    if base_name not in vgroups:
        return
    main_name, t1, t2, t3 = twist_names
    base_group = vgroups[base_name]
    for n in twist_names:
        if n not in vgroups:
            vgroups.new(name=n)
    rec_group = vgroups[reclaim_group] if (reclaim_group and reclaim_group in vgroups) else None
    levels = [
        (base_group, 0.0),
        (vgroups[t1], 0.25),
        (vgroups[t2], 0.50),
        (vgroups[t3], 0.75),
        (vgroups[main_name], 1.0),
    ]

    pb = obj.pose.bones.get(base_name)
    if pb is None:
        return
    head_w = obj.matrix_world @ pb.head
    tail_w = obj.matrix_world @ pb.tail
    axis = tail_w - head_w
    L = axis.length
    if L < 1e-6:
        return
    axis_n = axis / L
    span = max(tau_hi - tau_lo, 1e-6)
    rspan = max(RECLAIM_HI - RECLAIM_LO, 1e-6)

    for v in mesh.data.vertices:
        w = 0.0
        wrec = 0.0
        for g in v.groups:
            if g.group == base_group.index:
                w = g.weight
            elif rec_group and g.group == rec_group.index:
                wrec = g.weight
        if w <= 0 and wrec <= 0:
            continue

        t = ((mesh.matrix_world @ v.co) - head_w).dot(axis_n) / L

        rfrac = 0.0
        if wrec > 0:
            if t <= RECLAIM_LO:
                rfrac = 1.0
            elif t < RECLAIM_HI:
                rfrac = (RECLAIM_HI - t) / rspan
        pool = w + wrec * rfrac
        if pool <= 1e-6:
            continue

        if w > 0:
            base_group.remove([v.index])
        if rec_group and rfrac > 1e-6:
            rem = wrec * (1.0 - rfrac)
            if rem > 1e-6:
                rec_group.add([v.index], rem, 'REPLACE')
            else:
                rec_group.remove([v.index])

        tau = max(0.0, min(1.0, (t - tau_lo) / span))

        for k in range(len(levels) - 1):
            f0 = levels[k][1]
            f1 = levels[k + 1][1]
            if (f0 <= tau <= f1) or (k == len(levels) - 2):
                a = (tau - f0) / (f1 - f0) if f1 > f0 else 0.0
                a = max(0.0, min(1.0, a))
                if (1.0 - a) * pool > 1e-6:
                    levels[k][0].add([v.index], (1.0 - a) * pool, 'ADD')
                if a * pool > 1e-6:
                    levels[k + 1][0].add([v.index], a * pool, 'ADD')
                break
