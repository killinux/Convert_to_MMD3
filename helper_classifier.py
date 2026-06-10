"""Helper bone classifier — position+parent based classification of non-standard bones.

Takes the skeleton identifier's mapping and classifies all remaining bones
into categories used by the pipeline (twist candidates, pelvis, preserve, etc.).
All geometric thresholds are fractions of skeleton height (scale-free), and
dangling chains (skirt/hair/tail/ribbon strands — physics candidates in MMD)
are detected structurally and preserved whole, before any merge rule can
swallow their roots.

Categories:
    mapped   — already identified by skeleton_identifier
    twist    — on an arm segment; its weight is folded into the segment pool
               and re-graded by the twist split (weights/fold.py consumes this)
    pelvis   — shallow centered pelvis helper: weights map directly to 下半身
    preserve — keep bone and XPS weights (physics chains: skirt/hair/tail/
               breast/wing; thigh/butt helpers)
    control  — non-deform control bones, transfer weights out
    ignore   — _dummy_/_shadow_/leaf with no significance
    other    — unclassified; 'unused'-named ones get their weights re-homed
               per-vertex to the nearest deform bone, the rest are kept
"""

from mathutils import Vector  # noqa: F401  (kept for API parity / external users)

CENTER_EPS = 0.012   # |x| below this fraction of height counts as centered
CHAIN_MIN_DEPTH = 3  # subtree depth that makes a helper a physics strand


def classify_helpers(armature_data, skeleton_map):
    """Classify all non-standard bones by position + parent relationship.

    Args:
        armature_data: bpy.types.Armature
        skeleton_map: dict from identify_skeleton()

    Returns:
        dict: {bone_name: category_string}
    """
    bones = armature_data.bones
    mapped = set(v for v in skeleton_map.values() if v)

    zs = [b.head_local.z for b in bones]
    H = (max(zs) - min(zs)) if bones else 0.0
    if H < 1e-9:
        H = 1.0
    lat_eps = H * CENTER_EPS

    segments = _build_segments(bones, skeleton_map)
    # pelvis anchor: the bone owning the hip area — 下半身 since the fork→下半身
    # remap; center_bone kept as fallback for manually-filled presets.
    anchor_name = (skeleton_map.get("lower_body_bone", "")
                   or skeleton_map.get("center_bone", ""))
    anchor_ancestors = set()
    if anchor_name and bones.get(anchor_name):
        cur = bones.get(anchor_name).parent
        while cur:
            if cur.name not in mapped:
                anchor_ancestors.add(cur.name)
            cur = cur.parent
    thigh_names = {skeleton_map.get("left_thigh_bone", ""),
                   skeleton_map.get("right_thigh_bone", "")} - {""}
    spine_names = {skeleton_map.get(k, "") for k in (
        "upper_body_bone", "upper_body1_bone", "upper_body2_bone",
        "upper_body3_bone")} - {""}

    head_name = skeleton_map.get("head_bone", "")
    hand_names = {skeleton_map.get("left_hand_bone", ""),
                  skeleton_map.get("right_hand_bone", "")} - {""}

    result = {}
    for bone in bones:
        name = bone.name
        if name in mapped:
            result[name] = "mapped"
            continue
        if name.startswith(("_dummy_", "_shadow_")):
            result[name] = "ignore"
            continue

        # Physics strands: a non-mapped bone rooting a chain of 3+ bones is a
        # skirt/hair/tail/ribbon strand — preserve the whole chain so the user
        # can add rigid bodies/joints later. Checked before the segment /
        # pelvis rules so strand roots can't be merged away. Two exemptions:
        #   * subtree contains a mapped bone → not a strand but an in-chain
        #     helper (Daz lShldrTwist parents the rest of the arm) — fall
        #     through so the segment rule can mark it foldable;
        #   * the chain RUNS ALONG an arm segment (foretwist 1→2→3 style
        #     twist chains stay foldable; a ribbon hanging OFF the forearm
        #     leaves the segment tube, a twist chain stays inside it).
        if (_chain_depth(bone) >= CHAIN_MIN_DEPTH
                and not _subtree_contains(bone, mapped)
                and not _runs_along_arm_segment(bone, segments)):
            result[name] = "preserve"
            continue

        # Head descendants (hair/face). Strand-like ones were already caught
        # above; what remains are face bones (jaw/eyelids) — keep as 'other'
        # so their weights stay put.
        if head_name and _is_descendant_of(bone, head_name):
            result[name] = "other"
            continue

        # Hand descendants (carpals, extra finger bones)
        if hand_names and _is_descendant_of_any(bone, hand_names):
            result[name] = "other"
            continue

        # Centered unmapped ANCESTORS of the pelvis anchor (a 'root hips' or
        # helper bone the spine threads through above 下半身): their weights
        # belong to 下半身 — left in place they'd be dead bones whose skin
        # never follows the hips.
        if name in anchor_ancestors and abs(bone.head_local.x) < lat_eps:
            result[name] = "pelvis"
            continue

        ancestor = _find_mapped_ancestor(bone, mapped)

        # Pelvis: DIRECT shallow child of the anchor, centered
        if ancestor == anchor_name and anchor_name:
            is_direct = bone.parent and bone.parent.name == anchor_name
            if is_direct and abs(bone.head_local.x) < lat_eps:
                result[name] = "pelvis"
            elif abs(bone.head_local.x) >= lat_eps:
                result[name] = "preserve"
            else:
                result[name] = "other"
            continue

        seg_type = _closest_segment_type(bone, segments)
        if seg_type in ("upper_arm", "forearm"):
            result[name] = "twist"
            continue
        if seg_type == "thigh":
            result[name] = "preserve"
            continue

        if ancestor in thigh_names:
            result[name] = "preserve"
            continue
        if ancestor in spine_names:
            if abs(bone.head_local.x) >= lat_eps:
                result[name] = "preserve"  # breast/chest helper
            else:
                result[name] = "merge"  # intermediate spine segment — merge to nearest
            continue

        result[name] = "other"

    # propagate 'preserve' down whole strands: every non-mapped descendant of
    # a preserved bone is preserved (a strand is kept or folded as one unit).
    changed = True
    while changed:
        changed = False
        for bone in bones:
            name = bone.name
            if result.get(name) in ("mapped", "preserve", "ignore"):
                continue
            if bone.parent is not None and result.get(bone.parent.name) == "preserve":
                result[name] = "preserve"
                changed = True

    return result


def summary(classification):
    """Print a summary of the classification."""
    from collections import Counter
    counts = Counter(classification.values())
    lines = []
    for cat in ("mapped", "twist", "pelvis", "preserve", "merge", "control", "ignore", "other"):
        n = counts.get(cat, 0)
        if n:
            names = [k for k, v in classification.items() if v == cat]
            preview = ", ".join(names[:5])
            if len(names) > 5:
                preview += f" ... (+{len(names) - 5})"
            lines.append(f"  {cat:10s} {n:3d}  {preview}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _chain_depth(bone, max_depth=12):
    """Depth of the subtree rooted at bone (1 = leaf)."""
    if not bone.children or max_depth <= 0:
        return 1
    return 1 + max(_chain_depth(c, max_depth - 1) for c in bone.children)


def _subtree_contains(bone, names, max_depth=24):
    """True if any descendant of `bone` is in `names`."""
    if max_depth <= 0:
        return False
    for c in bone.children:
        if c.name in names or _subtree_contains(c, names, max_depth - 1):
            return True
    return False


def _deepest_descendant(bone, max_depth=12):
    cur = bone
    for _ in range(max_depth):
        if not cur.children:
            break
        cur = max(cur.children, key=_chain_depth)
    return cur


def _runs_along_arm_segment(bone, segments):
    """True if both the bone AND its chain end sit inside an arm segment's
    tube — the signature of an in-chain/child twist chain, as opposed to a
    ribbon/sleeve strand that starts near the arm but hangs away from it."""
    if _closest_segment_type(bone, segments) not in ("upper_arm", "forearm"):
        return False
    end = _deepest_descendant(bone)
    if end is bone:
        return True
    return _closest_segment_type(end, segments) in ("upper_arm", "forearm")


def _build_segments(bones, smap):
    """Build body segment definitions from skeleton map."""
    segments = []
    for side in ("left", "right"):
        pairs = [
            ("upper_arm", f"{side}_upper_arm_bone", f"{side}_lower_arm_bone"),
            ("forearm", f"{side}_lower_arm_bone", f"{side}_hand_bone"),
            ("thigh", f"{side}_thigh_bone", f"{side}_calf_bone"),
        ]
        for seg_type, from_key, to_key in pairs:
            from_name = smap.get(from_key, "")
            to_name = smap.get(to_key, "")
            if not from_name or not to_name:
                continue
            from_bone = bones.get(from_name)
            to_bone = bones.get(to_name)
            if not from_bone or not to_bone:
                continue
            seg_vec = to_bone.head_local - from_bone.head_local
            seg_len = seg_vec.length
            if seg_len < 1e-5:
                continue
            segments.append((seg_type, from_bone.head_local, to_bone.head_local, seg_len))
    return segments


def _closest_segment_type(bone, segments):
    """Find which body segment a bone is closest to (if any)."""
    best_type = None
    best_perp = float("inf")
    pos = bone.head_local

    for seg_type, seg_from, seg_to, seg_len in segments:
        seg = seg_to - seg_from
        L_sq = seg.length_squared
        if L_sq < 1e-8:
            continue
        t = (pos - seg_from).dot(seg) / L_sq
        if not (-0.15 <= t <= 1.15):
            continue
        t_c = max(0.0, min(1.0, t))
        proj = seg_from + t_c * seg
        perp = (pos - proj).length
        if perp < seg_len * 0.35 and perp < best_perp:
            best_perp = perp
            best_type = seg_type

    return best_type


def _find_mapped_ancestor(bone, mapped_names):
    """Walk parent chain to find the first mapped ancestor."""
    cur = bone.parent
    while cur:
        if cur.name in mapped_names:
            return cur.name
        cur = cur.parent
    return None


def _is_descendant_of(bone, ancestor_name):
    """Check if bone is a descendant of the named bone."""
    cur = bone.parent
    while cur:
        if cur.name == ancestor_name:
            return True
        cur = cur.parent
    return False


def _is_descendant_of_any(bone, ancestor_names):
    """Check if bone is a descendant of any of the named bones."""
    cur = bone.parent
    while cur:
        if cur.name in ancestor_names:
            return True
        cur = cur.parent
    return False
