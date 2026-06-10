"""Auto skeleton identifier — pure topology+geometry bone role detection.

Analyzes any humanoid armature and produces a bone role mapping dict
(same format as preset JSON files). No bone name dependency for the core
decisions; bone names are only used as low-weight tie-breaker hints (twist/
elbow keywords), so garbage names still identify.

Generalisation contract (the "any XPS" requirements this file owns):
  * scale-free      — every geometric threshold is a fraction of skeleton
                      height H, so raw XPS scale (~10x), metric and chibi
                      models all identify identically.
  * decoration-safe — skirt/hair/wing/coat chains cannot steal the leg/arm
                      forks: fork candidates are validated by limb evidence
                      (hand signature for arms, ground-reach + arclength +
                      foot-turn for legs).
  * in-chain twist  — Daz/UE style pass-through twist bones inside the arm
                      chain (lShldrTwist, lForearmTwist...) are skipped by a
                      joint-scoring segmentation, instead of being mis-mapped
                      to elbow/wrist slots.
  * pose-free       — works for A-pose and T-pose (joint scoring does not
                      require a bent elbow).

Algorithm:
1. Find spine chain: trace from highest centered bone down to the root.
2. Find fork points where validated leg/arm chains branch off laterally.
3. Map spine segment bones to MMD roles.
4. Trace arm chains, segment them into shoulder/upper/elbow/hand by joint
   scoring (skipping in-chain twist bones), then classify fingers.
5. Trace leg chains: thigh/calf/foot/toe (skipping overlapping control bones).
6. Find eye bones near head (symmetric pair, eye-name bonus).
"""

import re

from mathutils import Vector


# All eps constants are fractions of skeleton height H. The absolute values
# they replace were calibrated on a 1.7 m rig: 0.006*1.7 ≈ 0.01, 0.012*1.7 ≈ 0.02,
# so behaviour at metric scale is unchanged while other scales now work.
CENTER_EPS = 0.006      # |x| below this fraction of H counts as "centered"
WIDE_CENTER_EPS = 0.012
SYM_EPS = 0.006         # symmetric-pair coordinate tolerance (eyes)
EYE_MIN_X = 0.012

# joint-scoring name hints (tie-breakers only — never load-bearing)
_TWIST_NAME_RE = re.compile(r"twist|roll|捩|ねじ", re.IGNORECASE)
_ELBOW_NAME_RE = re.compile(r"elbow|forearm|fore_?arm|lower_?arm|loarm|ひじ|肘", re.IGNORECASE)


def identify_skeleton(armature_data):
    """Analyze armature topology and geometry to identify bone roles.

    Args:
        armature_data: bpy.types.Armature (armature.data)

    Returns:
        dict matching preset JSON format with bone names filled in.
    """
    bones = armature_data.bones
    result = _empty_result()
    if not bones or len(bones) < 3:
        return result

    H = _skeleton_height(bones)
    if H < 1e-6:
        return result

    spine = _find_spine_chain(bones, H)
    if len(spine) < 2:
        return result

    leg_idx, arm_idx = _find_fork_points(spine, H)

    _map_spine(spine, leg_idx, arm_idx, result, H)

    if arm_idx is not None:
        _map_arms(spine, arm_idx, result, H)

    if leg_idx is not None:
        _map_legs(spine, leg_idx, result, H)

    if result["head_bone"]:
        _map_eyes(bones, result["head_bone"], result, H)

    return result


def _skeleton_height(bones):
    zs = [b.head_local.z for b in bones]
    return max(zs) - min(zs)


# ---------------------------------------------------------------------------
# Spine chain detection
# ---------------------------------------------------------------------------

def _find_spine_chain(bones, H):
    """Find the spine chain by tracing from the highest center bone to root."""
    x_thresh = H * 0.1
    lat_eps = H * CENTER_EPS

    center = [b for b in bones if abs(b.head_local.x) < x_thresh]
    if not center:
        center = sorted(bones, key=lambda b: abs(b.head_local.x))[:5]

    # The head bone has bilateral children (both +X and -X sides: eyes, jaw, etc.)
    # Score by Z position + children bonus (head typically has many more children
    # than jaw/eye).
    bilateral = [b for b in center
                 if any(c.head_local.x > lat_eps for c in b.children)
                 and any(c.head_local.x < -lat_eps for c in b.children)]
    if bilateral:
        top = max(bilateral,
                  key=lambda b: b.head_local.z + 0.01 * H * min(len(b.children), 50))
    else:
        with_ch = [b for b in center if b.children]
        top = max(with_ch or center, key=lambda b: b.head_local.z)

    chain = []
    cur = top
    while cur:
        chain.append(cur)
        cur = cur.parent
    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Fork detection (with limb validation, so decoration chains can't win)
# ---------------------------------------------------------------------------

def _chain_arclength_and_low(bone, max_depth=12):
    """Follow the deepest path from `bone`; return (arclength, lowest z, path)."""
    path = [bone]
    cur = bone
    for _ in range(max_depth):
        if not cur.children:
            break
        cur = max(cur.children, key=_subtree_depth)
        path.append(cur)
    arc = sum((path[i + 1].head_local - path[i].head_local).length
              for i in range(len(path) - 1))
    low = min(b.head_local.z for b in path)
    return arc, low, path


def _leg_evidence(candidate, H):
    """Score how leg-like the chain starting at `candidate` is (0 = not a leg)."""
    arc, low, path = _chain_arclength_and_low(candidate)
    start_z = candidate.head_local.z
    drop = start_z - low
    if arc < 0.25 * H or drop < 0.22 * H:
        return 0.0
    score = arc + 2.0 * drop
    # foot-turn bonus: some segment near the bottom turns mostly horizontal
    # (the foot) after a mostly-vertical run (the shin) — dress strands don't.
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        if a.head_local.z > low + 0.12 * H:
            continue
        seg = b.head_local - a.head_local
        if seg.length > 0.02 * H and abs(seg.z) < 0.6 * seg.length:
            score += 0.5 * H
            break
    return score


def _arm_evidence(candidate):
    """Score how arm-like the chain starting at `candidate` is (hand signature)."""
    if _has_hand_descendant(candidate):
        return 2.0 + _subtree_depth(candidate)
    return 0.0


def _lateral_candidates(bone, chain_set, x_thresh, min_depth=1):
    """Limb-start candidates among `bone`'s off-chain children, per side.

    A child counts as a left/right candidate if its OWN head is lateral, or —
    a clavicle root hugging the spine (|x| under threshold, e.g. XNALara
    'arm left shoulder 1' on some ports) — if any of its children is lateral.
    Without the second form, a chest bone whose only lateral-headed children
    are coat/jacket strands hides the real arms entirely.
    """
    left, right = [], []
    for c in bone.children:
        if c.name in chain_set or _subtree_depth(c) < min_depth:
            continue
        if c.head_local.x > x_thresh:
            left.append(c)
        elif c.head_local.x < -x_thresh:
            right.append(c)
        else:
            # a centered pass-through (Daz 'pelvis' parenting BOTH thighs)
            # is a candidate on every side its grandchildren reach
            if any(g.head_local.x > x_thresh for g in c.children):
                left.append(c)
            if any(g.head_local.x < -x_thresh for g in c.children):
                right.append(c)
    return left, right


def _find_fork_points(chain, H):
    """Find arm and leg fork indices on the spine chain.

    Returns (leg_fork_idx, arm_fork_idx). A fork qualifies as the leg fork
    only with leg evidence on both sides, as the arm fork only with arm
    evidence on both sides; among qualified candidates the lowest leg fork
    and the best-scoring arm fork win. Falls back to the old Z-order rule
    when no fork has positive evidence (degenerate rigs).
    """
    if len(chain) < 2:
        return None, None

    x_thresh = max(H * 0.01, H * CENTER_EPS)
    chain_set = {b.name for b in chain}
    forks = []  # (idx, left candidates, right candidates)

    for i, bone in enumerate(chain):
        # every bone except the chain tip may fork — XNALara default rigs
        # hang the shoulders off 'head neck lower', the second-to-last bone
        if i >= len(chain) - 1:
            continue
        left, right = _lateral_candidates(bone, chain_set, x_thresh, min_depth=3)
        if left and right:
            forks.append((i, left, right))

    if not forks:
        return None, None

    # validated candidates
    leg_cands = []
    arm_cands = []
    for i, left, right in forks:
        leg_l = max((_leg_evidence(c, H) for c in left), default=0.0)
        leg_r = max((_leg_evidence(c, H) for c in right), default=0.0)
        if leg_l > 0 and leg_r > 0:
            leg_cands.append((i, leg_l + leg_r))
        arm_l = max((_arm_evidence(c) for c in left), default=0.0)
        arm_r = max((_arm_evidence(c) for c in right), default=0.0)
        if arm_l > 0 and arm_r > 0:
            arm_cands.append((i, arm_l + arm_r))

    leg_idx = min(leg_cands, key=lambda t: chain[t[0]].head_local.z)[0] if leg_cands else None
    arm_idx = None
    if arm_cands:
        # best hand evidence; ties go to the higher fork (chest above hips)
        arm_idx = max(arm_cands, key=lambda t: (t[1], chain[t[0]].head_local.z))[0]
    if leg_idx is not None and arm_idx == leg_idx and len(arm_cands) > 1:
        others = [t for t in arm_cands if t[0] != leg_idx]
        if others:
            arm_idx = max(others, key=lambda t: (t[1], chain[t[0]].head_local.z))[0]

    if leg_idx is None and arm_idx is None:
        # no validated evidence — degenerate rig; fall back to Z ordering
        idxs = sorted({i for i, _, _ in forks}, key=lambda i: chain[i].head_local.z)
        if len(idxs) == 1:
            mid_z = (chain[0].head_local.z + chain[-1].head_local.z) / 2
            if chain[idxs[0]].head_local.z > mid_z:
                return None, idxs[0]
            return idxs[0], None
        return idxs[0], idxs[-1]

    return leg_idx, arm_idx


# ---------------------------------------------------------------------------
# Spine role mapping
# ---------------------------------------------------------------------------

def _map_spine(chain, leg_idx, arm_idx, result, H):
    """Assign spine chain bones to MMD roles."""
    lat_eps = H * CENTER_EPS

    if leg_idx is None and arm_idx is None:
        # Fallback: first = root, last = head, second-to-last = neck
        if len(chain) >= 2:
            result["all_parents_bone"] = chain[0].name
            result["head_bone"] = chain[-1].name
        if len(chain) >= 3:
            result["neck_bone"] = chain[-2].name
        return

    # Root / ground: bones before leg fork
    if leg_idx is not None and leg_idx > 0:
        result["all_parents_bone"] = chain[0].name

    # The leg fork bone is the pelvis — MMD's 下半身, the DEFORM bone that
    # owns the hip weights. It must NOT be mapped to センター: センター is a
    # weightless control bone that `complete` builds from scratch; renaming a
    # weighted pelvis bone to センター gets its skin wiped by the control-bone
    # cleanup (real-rig failure: a port whose legs hang off 'spine lower').
    if leg_idx is not None:
        result["lower_body_bone"] = chain[leg_idx].name

    if arm_idx is None:
        # Only leg fork found — map remaining chain above legs
        above = chain[leg_idx + 1:]
        if len(above) >= 1:
            result["upper_body2_bone"] = above[0].name
        if len(above) >= 3:
            result["upper_body_bone"] = above[0].name
            result["upper_body2_bone"] = above[1].name
            result["neck_bone"] = above[-2].name if len(above) >= 3 else ""
            result["head_bone"] = above[-1].name
        elif len(above) == 2:
            result["neck_bone"] = above[0].name
            result["head_bone"] = above[1].name
        elif len(above) == 1:
            result["head_bone"] = above[0].name
        return

    if leg_idx is None:
        # Only arm fork found — set center as root
        result["center_bone"] = chain[0].name

    # Spine segments between hips and the chest. Normally the arm fork bone
    # IS the chest (上半身2). XNALara default rigs instead hang the shoulders
    # off the neck root ('head neck lower', one bone under the head): when
    # only the head remains above the fork, the fork bone is the NECK and the
    # chest is the bone just below it.
    start = (leg_idx + 1) if leg_idx is not None else 1
    above = chain[arm_idx + 1:]
    chest_idx = arm_idx
    if len(above) == 1 and arm_idx - 1 >= start:
        chest_idx = arm_idx - 1
        result["neck_bone"] = chain[arm_idx].name
        result["head_bone"] = above[0].name
    elif len(above) >= 2:
        result["head_bone"] = above[-1].name
        result["neck_bone"] = above[0].name
    elif len(above) == 1:
        result["head_bone"] = above[0].name

    spine_seg = chain[start:chest_idx]
    if len(spine_seg) >= 1:
        result["upper_body_bone"] = spine_seg[0].name
    if len(spine_seg) >= 2:
        result["upper_body1_bone"] = spine_seg[1].name
    # chest bone = upper_body2
    result["upper_body2_bone"] = chain[chest_idx].name


# ---------------------------------------------------------------------------
# Arm detection
# ---------------------------------------------------------------------------

def _map_arms(chain, arm_idx, result, H):
    """Identify arm chains from the arm fork point."""
    fork_bone = chain[arm_idx]
    chain_set = {b.name for b in chain}
    x_thresh = max(H * 0.01, H * CENTER_EPS)

    left, right = _lateral_candidates(fork_bone, chain_set, x_thresh)

    left_start = _pick_arm_start(left)
    right_start = _pick_arm_start(right)

    if left_start:
        _assign_arm(left_start, True, result, H)
    if right_start:
        _assign_arm(right_start, False, result, H)


def _pick_arm_start(candidates):
    """Among lateral children, pick the one most likely to be the arm chain start."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    with_hand = [c for c in candidates if _has_hand_descendant(c)]
    if with_hand:
        return max(with_hand, key=_subtree_depth)
    return max(candidates, key=_subtree_depth)


def _trace_arm_chain(start, max_depth=10):
    """Trace the arm chain from its start, preferring the path that reaches a
    hand; stop at the hand bone."""
    chain = [start]
    cur = start
    for _ in range(max_depth):
        if _is_hand_bone(cur) and len(chain) >= 2:
            break
        children = list(cur.children)
        if not children:
            break
        with_hand = [c for c in children if _has_hand_descendant(c)]
        pool = with_hand or children
        best = max(pool, key=_subtree_depth)
        chain.append(best)
        cur = best
    return chain


def _segment_arm_chain(nodes, hand_i):
    """Pick (shoulder_i or None, upper_i, elbow_i) from nodes[0..hand_i].

    The classic 4-node chain (shoulder→upper→elbow→hand) maps positionally —
    that assignment is always right and joint scoring must never override it
    (a short clavicle can fool any length prior: verified on a real XNALara
    rig where scoring once picked the clavicle as the upper arm).

    Scoring is used only when the chain carries EXTRA nodes — in-chain twist
    bones (Daz lShldrTwist/lForearmTwist, split UE chains) — or is a 3-node
    chain (no clavicle). Among all (upper, elbow) interior pairs it prefers
    anatomically balanced segment lengths (upper ≈ 1.1 × forearm) with
    name-hint tie-breakers. No bend term: a clavicle kink fakes a bend while
    T-pose elbows have none. Works in T-pose.
    """
    if hand_i < 2:
        return None, None, None
    if hand_i == 3:
        return 0, 1, 2
    hand_head = nodes[hand_i].head_local

    best = None
    best_score = -1e18
    for i_up in range(0, hand_i - 1):
        for i_el in range(i_up + 1, hand_i):
            upper_len = (nodes[i_el].head_local - nodes[i_up].head_local).length
            fore_len = (hand_head - nodes[i_el].head_local).length
            if upper_len < 1e-9 or fore_len < 1e-9:
                continue
            ratio = upper_len / fore_len
            score = -abs(ratio - 1.1)
            # name hints (tie-breakers): twist-named bones make bad joints,
            # elbow/forearm-named bones make good elbows.
            if _TWIST_NAME_RE.search(nodes[i_el].name):
                score -= 1.5
            if _TWIST_NAME_RE.search(nodes[i_up].name):
                score -= 1.5
            if _ELBOW_NAME_RE.search(nodes[i_el].name):
                score += 0.6
            # prefer the longest coverage: upper arm should start as close to
            # the torso as possible (skip only what must be skipped)
            score -= 0.05 * i_up
            if score > best_score:
                best_score = score
                best = (i_up, i_el)

    if best is None:
        return None, None, None
    i_up, i_el = best
    shoulder_i = i_up - 1 if i_up >= 1 else None
    return shoulder_i, i_up, i_el


def _assign_arm(start, is_left, result, H):
    """Trace arm chain and assign shoulder/upper_arm/forearm/hand/fingers."""
    side = "left" if is_left else "right"
    arm = _trace_arm_chain(start)

    # locate the hand (signature: 3+ finger-like chains)
    hand_i = None
    for i, b in enumerate(arm):
        if i >= 2 and _is_hand_bone(b):
            hand_i = i
            break
    if hand_i is None:
        hand_i = len(arm) - 1

    if hand_i >= 2:
        sh_i, up_i, el_i = _segment_arm_chain(arm, hand_i)
        if up_i is not None:
            if sh_i is not None:
                result[f"{side}_shoulder_bone"] = arm[sh_i].name
            result[f"{side}_upper_arm_bone"] = arm[up_i].name
            result[f"{side}_lower_arm_bone"] = arm[el_i].name
            result[f"{side}_hand_bone"] = arm[hand_i].name
            _identify_fingers(arm[hand_i], is_left, result)
            return

    # degenerate short chains
    if len(arm) == 2:
        result[f"{side}_upper_arm_bone"] = arm[0].name
        result[f"{side}_hand_bone"] = arm[1].name
        _identify_fingers(arm[1], is_left, result)


def _is_hand_bone(bone):
    """True if bone has 3+ children with finger-like chains (depth >= 3)."""
    children = list(bone.children)
    if len(children) < 3:
        return False
    deep = sum(1 for c in children if _subtree_depth(c) >= 3)
    return deep >= 3


def _has_hand_descendant(bone, depth=8):
    """Check if bone or any descendant within depth is a hand bone."""
    if _is_hand_bone(bone):
        return True
    if depth <= 0:
        return False
    return any(_has_hand_descendant(c, depth - 1) for c in bone.children)


# ---------------------------------------------------------------------------
# Finger detection
# ---------------------------------------------------------------------------

def _identify_fingers(hand_bone, is_left, result):
    """Classify finger chains branching from the hand bone.

    Thumb = the chain whose root sits closest to the wrist AND deviates most
    from the common finger direction. Remaining fingers are ordered by signed
    position along the palm-lateral axis away from the thumb (robust to
    per-finger reach differences, unlike distance-from-thumb sorting).
    """
    children = list(hand_bone.children)
    chains = []
    for child in children:
        ch = [child]
        cur = child
        while len(cur.children) == 1:
            ch.append(cur.children[0])
            cur = cur.children[0]
        if len(ch) >= 2:
            chains.append(ch)

    if len(chains) < 2:
        return

    # Strip leading carpal bones (4+ bone chain where first bone is a pass-through)
    for i, ch in enumerate(chains):
        if len(ch) >= 4:
            chains[i] = ch[1:]

    side = "left" if is_left else "right"
    hand_pos = hand_bone.head_local

    dirs = [(ch[0].head_local - hand_pos).normalized() for ch in chains]
    dists = [(ch[0].head_local - hand_pos).length for ch in chains]
    max_dist = max(dists) or 1.0
    avg = Vector((0, 0, 0))
    for d in dirs:
        avg += d
    avg /= len(dirs)

    # thumb score: direction deviation + root proximity to the wrist
    scores = [(dirs[i] - avg).length + (1.0 - dists[i] / max_dist)
              for i in range(len(chains))]
    thumb_i = scores.index(max(scores))
    thumb = chains.pop(thumb_i)
    thumb_root = thumb[0].head_local

    for i, bone in enumerate(thumb[:3]):
        result[f"{side}_thumb_{i}"] = bone.name

    # order the remaining fingers along the palm-lateral axis pointing away
    # from the thumb: index closest to the thumb side, pinky farthest.
    roots = [ch[0].head_local for ch in chains]
    centroid = Vector((0, 0, 0))
    for r in roots:
        centroid += r
    centroid /= len(roots)
    fwd = (centroid - hand_pos).normalized()
    lat = (centroid - thumb_root) - fwd * (centroid - thumb_root).dot(fwd)
    if lat.length > 1e-9:
        lat.normalize()
        chains.sort(key=lambda ch: (ch[0].head_local - thumb_root).dot(lat))
    else:
        chains.sort(key=lambda ch: (ch[0].head_local - thumb_root).length)

    names = ["index", "middle", "ring", "pinky"]
    for fi, ch in enumerate(chains[:4]):
        for si, bone in enumerate(ch[:3]):
            result[f"{side}_{names[fi]}_{si + 1}"] = bone.name


# ---------------------------------------------------------------------------
# Leg detection
# ---------------------------------------------------------------------------

def _map_legs(chain, leg_idx, result, H):
    """Identify leg chains from the leg fork point."""
    fork_bone = chain[leg_idx]
    chain_set = {b.name for b in chain}
    x_thresh = max(H * 0.01, H * CENTER_EPS)

    off = [c for c in fork_bone.children if c.name not in chain_set]
    left = [c for c in off if c.head_local.x > x_thresh]
    right = [c for c in off if c.head_local.x < -x_thresh]

    # If no direct lateral children, check grandchildren
    if not left or not right:
        for oc in off:
            gc_left = [c for c in oc.children if c.head_local.x > x_thresh]
            gc_right = [c for c in oc.children if c.head_local.x < -x_thresh]
            if gc_left and not left:
                left = gc_left
            if gc_right and not right:
                right = gc_right

    # leg evidence first (so a deep skirt strand can't beat the actual leg),
    # subtree depth as fallback
    def _pick(cands):
        if not cands:
            return None
        scored = [(c, _leg_evidence(c, H)) for c in cands]
        with_leg = [t for t in scored if t[1] > 0]
        if with_leg:
            return max(with_leg, key=lambda t: t[1])[0]
        return max(cands, key=_subtree_depth)

    lbest = _pick(left)
    rbest = _pick(right)
    if lbest:
        _assign_leg(lbest, True, result, H)
    if rbest:
        _assign_leg(rbest, False, result, H)


def _segment_leg_chain(nodes, H):
    """Pick (thigh_i, knee_i, ankle_i) from a traced leg chain.

    Joint anatomy instead of positional slots, so chains carrying extra
    bones — leading corrective bones (Daz-port c_thigh_b.l) or in-chain
    thigh twist — assign correctly:
      ankle = first node (index>=2) at ankle height (z < 0.12H),
      knee  = node whose height is closest to the hip↔ankle midpoint
              (twist/roll-named nodes penalised),
      thigh = the LATEST node above the knee whose thigh/shin length ratio
              is anatomically plausible (skips leading correctives), falling
              back to the best ratio (skips in-chain thigh twist).
    Returns None when no node reaches ankle height (degenerate rig) — the
    caller then uses the positional fallback.
    """
    ankle_i = None
    for i in range(2, len(nodes)):
        if nodes[i].head_local.z < 0.12 * H:
            ankle_i = i
            break
    if ankle_i is None or ankle_i < 2:
        return None
    ankle_z = nodes[ankle_i].head_local.z
    hip_z = nodes[0].head_local.z
    mid_z = (hip_z + ankle_z) / 2.0

    knee_i = None
    best = None
    for i in range(1, ankle_i):
        score = -abs(nodes[i].head_local.z - mid_z)
        if _TWIST_NAME_RE.search(nodes[i].name):
            score -= 0.5 * H
        if best is None or score > best:
            best = score
            knee_i = i

    shin_len = (nodes[ankle_i].head_local - nodes[knee_i].head_local).length
    if shin_len < 1e-9:
        return None
    scored = []
    for i in range(0, knee_i):
        thigh_len = (nodes[knee_i].head_local - nodes[i].head_local).length
        scored.append((i, abs(thigh_len / shin_len - 1.05)))
    plausible = [i for i, d in scored if d < 0.25]
    thigh_i = max(plausible) if plausible else min(scored, key=lambda t: t[1])[0]
    return thigh_i, knee_i, ankle_i


def _assign_leg(start, is_left, result, H):
    """Trace leg chain and assign thigh/shin/foot/toe."""
    side = "left" if is_left else "right"
    chain = _trace_limb_chain(start, max_depth=8)

    # Skip control bones (腰キャンセル) at chain start: head overlaps next bone
    if len(chain) >= 2:
        d = (chain[0].head_local - chain[1].head_local).length
        if d < H * CENTER_EPS:
            chain = chain[1:]

    if len(chain) >= 3:
        seg = _segment_leg_chain(chain, H)
        if seg is not None:
            thigh_i, knee_i, ankle_i = seg
            result[f"{side}_thigh_bone"] = chain[thigh_i].name
            result[f"{side}_calf_bone"] = chain[knee_i].name
            result[f"{side}_foot_bone"] = chain[ankle_i].name
            # toe (足先EX) must sit meaningfully FORWARD of the ankle — Daz
            # lMetatarsals' head is at the heel (mm from the ankle head):
            # using it gives 足首 a degenerate backward direction. Walk the
            # chain past such nodes to the real toe; none found → complete
            # synthesises a ground-forward toe instead.
            ankle_head = chain[ankle_i].head_local
            for j in range(ankle_i + 1, len(chain)):
                if chain[j].head_local.y < ankle_head.y - 0.02 * H:
                    result[f"{side}_toe_bone"] = chain[j].name
                    break
            return

    # positional fallback (degenerate / short chains)
    if len(chain) >= 4:
        result[f"{side}_thigh_bone"] = chain[0].name
        result[f"{side}_calf_bone"] = chain[1].name
        result[f"{side}_foot_bone"] = chain[2].name
        result[f"{side}_toe_bone"] = chain[3].name
    elif len(chain) == 3:
        result[f"{side}_thigh_bone"] = chain[0].name
        result[f"{side}_calf_bone"] = chain[1].name
        result[f"{side}_foot_bone"] = chain[2].name
    elif len(chain) == 2:
        result[f"{side}_thigh_bone"] = chain[0].name
        result[f"{side}_calf_bone"] = chain[1].name


def _trace_limb_chain(start, max_depth=6):
    """Trace a limb chain, following the child with the deepest subtree."""
    chain = [start]
    cur = start
    for _ in range(max_depth):
        children = list(cur.children)
        if not children:
            break
        if len(children) == 1:
            chain.append(children[0])
            cur = children[0]
        else:
            best = max(children, key=_subtree_depth)
            chain.append(best)
            cur = best
    return chain


# ---------------------------------------------------------------------------
# Eye detection
# ---------------------------------------------------------------------------

def _is_eye_name(name):
    """True if a bone name looks like an eyeball (not eyelid/eyebrow/eyelash)."""
    n = name.lower()
    if any(bad in n for bad in ("eyelid", "eyebrow", "eyelash", "brow", "lash")):
        return False
    return ("eyeball" in n) or ("eye" in n) or ("目" in n)


def _map_eyes(bones, head_name, result, H):
    """Find symmetric eye bones among head's children/grandchildren."""
    head = bones.get(head_name)
    if not head:
        return

    candidates = []
    for child in head.children:
        candidates.append(child)
        for gc in child.children:
            candidates.append(gc)

    # Find symmetric pairs by matching |X| and Z. Order-independent: pair every
    # +X (left) candidate with every -X (right) candidate.
    best_pair = None
    best_score = -float('inf')
    x_min = H * EYE_MIN_X
    sym_tol = H * SYM_EPS
    lefts = [c for c in candidates if c.head_local.x > x_min]
    rights = [c for c in candidates if c.head_local.x < -x_min]
    for c1 in lefts:
        for c2 in rights:
            dx = abs(abs(c1.head_local.x) - abs(c2.head_local.x))
            dz = abs(c1.head_local.z - c2.head_local.z)
            dy = abs(c1.head_local.y - c2.head_local.y)
            if dx < sym_tol and dz < sym_tol and dy < sym_tol:
                # Prefer the highest pair (eyes are above lips/nose);
                # strongly prefer bones whose names look like eyes (avoid
                # picking symmetric hair bones over real eyeball bones).
                score = c1.head_local.z + c2.head_local.z
                if _is_eye_name(c1.name) and _is_eye_name(c2.name):
                    score += 1000.0 * H
                if score > best_score:
                    best_score = score
                    best_pair = (c1, c2)

    if best_pair:
        left = best_pair[0] if best_pair[0].head_local.x > 0 else best_pair[1]
        right = best_pair[1] if best_pair[0].head_local.x > 0 else best_pair[0]
        result["left_eye_bone"] = left.name
        result["right_eye_bone"] = right.name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_depth_cache = {}


def _subtree_depth(bone, max_depth=20):
    """Depth of subtree rooted at bone (cached)."""
    key = bone.name
    if key in _depth_cache:
        return _depth_cache[key]
    if not bone.children or max_depth <= 0:
        _depth_cache[key] = 1
        return 1
    d = 1 + max(_subtree_depth(c, max_depth - 1) for c in bone.children)
    _depth_cache[key] = d
    return d


def clear_cache():
    """Clear the subtree depth cache (call between different armatures)."""
    _depth_cache.clear()


def _empty_result():
    """Return preset dict template with all keys empty."""
    return {
        "all_parents_bone": "",
        "center_bone": "",
        "groove_bone": "",
        "hip_bone": "",
        "upper_body_bone": "",
        "upper_body1_bone": "",
        "upper_body2_bone": "",
        "upper_body3_bone": "",
        "neck_bone": "",
        "head_bone": "",
        "left_shoulder_bone": "",
        "right_shoulder_bone": "",
        "left_upper_arm_bone": "",
        "right_upper_arm_bone": "",
        "left_lower_arm_bone": "",
        "right_lower_arm_bone": "",
        "left_hand_bone": "",
        "right_hand_bone": "",
        "lower_body_bone": "",
        "left_thigh_bone": "",
        "right_thigh_bone": "",
        "left_calf_bone": "",
        "right_calf_bone": "",
        "left_foot_bone": "",
        "right_foot_bone": "",
        "left_toe_bone": "",
        "right_toe_bone": "",
        "control_center_bone": "",
        "left_eye_bone": "",
        "right_eye_bone": "",
        "left_thumb_0": "",
        "left_thumb_1": "",
        "left_thumb_2": "",
        "right_thumb_0": "",
        "right_thumb_1": "",
        "right_thumb_2": "",
        "left_index_1": "",
        "left_index_2": "",
        "left_index_3": "",
        "right_index_1": "",
        "right_index_2": "",
        "right_index_3": "",
        "left_middle_1": "",
        "left_middle_2": "",
        "left_middle_3": "",
        "right_middle_1": "",
        "right_middle_2": "",
        "right_middle_3": "",
        "left_ring_1": "",
        "left_ring_2": "",
        "left_ring_3": "",
        "right_ring_1": "",
        "right_ring_2": "",
        "right_ring_3": "",
        "left_pinky_1": "",
        "left_pinky_2": "",
        "left_pinky_3": "",
        "right_pinky_1": "",
        "right_pinky_2": "",
        "right_pinky_3": "",
    }
