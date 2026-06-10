"""Fold planning: which deform pool should a helper bone's weight join?

Pure geometry, no bpy — the decisions are computed from bone-head positions
and per-helper weight centroids, so this module is offline-testable and the
bpy adapter (transfer.py) stays thin.

Why this exists (the "any XPS" weight gap): XPS game ports carry weighted
helper bones in three topologies — in-chain twist (Daz lShldrTwist), side-
child twist (UE upperarm_twist_01_l, Valve Ulna/Wrist), and bend correctives.
XPS has no constraints, so after conversion these bones are dead: VMD never
drives them and their vertices ride the parent rigidly — candy-wrap returns
on exactly the vertices the twist split can't see. The fix is position-driven
and conserving (no per-target magic): fold each helper's weight into the pool
bone of its host limb segment (腕/ひじ/手首) BEFORE the twist split, then let
the τ curve re-grade everything by vertex position, identically to weights
that were on the segment all along.

Decision ladder per helper (first match wins):
  deltoid  — shoulder-cap helper: split 肩/腕 by ramp (transfer.py owns the
             per-vertex ramp; this module only flags the host arm)
  segment  — weight centroid sits inside an arm/palm segment tube: fold the
             whole group into that segment's pool bone
  nearest  — everything else consumed: per-vertex nearest valid deform bone
             (the legacy behaviour, still right for spine/misc helpers)
"""

from mathutils import Vector  # noqa: F401  (Vector arithmetic on caller data)

# host-segment acceptance: along-axis param t and lateral distance as a
# fraction of segment length. Same tube the helper classifier uses (0.35) plus
# slack for caps/extremity helpers whose centroid sits slightly off-axis.
SEG_T_MIN = -0.15
SEG_T_MAX = 1.15
SEG_LATERAL_FRAC = 0.5


class Segment:
    __slots__ = ("kind", "origin", "axis", "length", "l2", "pool")

    def __init__(self, kind, a, b, pool):
        self.kind = kind
        self.origin = a
        self.axis = b - a
        self.l2 = self.axis.length_squared
        self.length = self.axis.length
        self.pool = pool

    def __repr__(self):
        return f"Segment({self.kind}, pool={self.pool})"


def build_arm_segments(get_head, sides=("左", "右")):
    """Build the fold target segments from MMD-named bones (post-rename).

    get_head(name) -> Vector or None (world space). Palm segment runs
    手首→中指１, falling back to half a forearm beyond the wrist when the
    middle finger is missing (mitten hands).
    """
    segs = []
    for s in sides:
        arm = get_head(f"{s}腕")
        el = get_head(f"{s}ひじ")
        wr = get_head(f"{s}手首")
        mid = get_head(f"{s}中指１")
        if arm is not None and el is not None and (el - arm).length_squared > 1e-12:
            segs.append(Segment("upper_arm", arm, el, f"{s}腕"))
        if el is not None and wr is not None and (wr - el).length_squared > 1e-12:
            segs.append(Segment("forearm", el, wr, f"{s}ひじ"))
        if wr is not None:
            end = mid
            if end is None and el is not None:
                end = wr + (wr - el) * 0.5
            if end is not None and (end - wr).length_squared > 1e-12:
                segs.append(Segment("palm", wr, end, f"{s}手首"))
    return segs


def host_segment(centroid, segments,
                 t_min=SEG_T_MIN, t_max=SEG_T_MAX, lateral_frac=SEG_LATERAL_FRAC):
    """Return the Segment whose tube contains `centroid` (min lateral), or None."""
    best = None
    best_lat = float("inf")
    for seg in segments:
        if seg.l2 < 1e-12:
            continue
        t = (centroid - seg.origin).dot(seg.axis) / seg.l2
        if not (t_min <= t <= t_max):
            continue
        tc = max(0.0, min(1.0, t))
        lat = (centroid - (seg.origin + seg.axis * tc)).length
        if lat < lateral_frac * seg.length and lat < best_lat:
            best_lat = lat
            best = seg
    return best


def plan_segment_folds(centroids, segments):
    """Map each helper to its host segment's pool bone.

    centroids: {helper_name: weight centroid Vector}
    Returns {helper_name: pool_bone_name} for the hosted ones only; helpers
    with no host segment are left to the per-vertex nearest fallback.
    """
    plan = {}
    for name, c in centroids.items():
        seg = host_segment(c, segments)
        if seg is not None:
            plan[name] = seg.pool
    return plan
