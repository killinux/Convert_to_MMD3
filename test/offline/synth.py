"""Parameterized synthetic humanoid skeletons in many XPS naming conventions.

Each builder returns (FakeArmatureData, expected) where `expected` maps the
skeleton_identifier role keys (left_upper_arm_bone, ...) to the bone names the
identifier OUGHT to produce. Geometry is anatomically plausible, Z-up,
+X = character left, ground at z=0 — exactly what XNALaraMesh imports give.

Structural axes covered (the variation found in real XPS exports):
  naming        xnalara / bip001 / valvebiped / ue4 / daz_g8 / garbage
  spine         2..6 segments between hips and neck
  shoulder      with / without clavicle
  toe           with / without
  twist bones   none / children-of-segment (UE,XPS foretwist) / in-chain (Daz)
  decoration    skirt chains, hair chains, wings, breast bones, "unused" helpers
  pose          A-pose / T-pose ; scale meters / raw XPS (~10x)
"""

import math

from mathutils import Vector
from fakes import FakeArmatureData


# ---------------------------------------------------------------------------
# proportion table (fractions of total height H)
# ---------------------------------------------------------------------------
P = {
    "hips_z": 0.52, "waist_z": 0.61, "chest_z": 0.70, "chest2_z": 0.78,
    "neck_z": 0.86, "head_z": 0.91, "top_z": 1.00,
    "shoulder_root_x": 0.012, "shoulder_joint_x": 0.105, "shoulder_z": 0.815,
    "upper_arm_len": 0.165, "forearm_len": 0.145, "hand_len": 0.10,
    "thigh_x": 0.052, "knee_z": 0.285, "ankle_z": 0.042,
    "foot_fwd": 0.085, "toe_fwd": 0.055,
    "eye_x": 0.019, "eye_z": 0.936, "eye_y": -0.05,
}


def _arm_dir(side_sign, pose):
    """Unit direction of the whole arm (A-pose 45° down, T-pose horizontal)."""
    if pose == "T":
        return Vector((side_sign, 0.0, 0.0))
    s = math.sqrt(0.5)
    return Vector((side_sign * s, 0.0, -s))


class Rig:
    """Builder helper that accumulates bones + the expected role mapping."""

    def __init__(self, height=1.7, pose="A"):
        self.arm = FakeArmatureData()
        self.H = height
        self.pose = pose
        self.expected = {}

    def b(self, name, frac_pos, parent=None, role=None, tail=None, use_deform=True):
        """Add bone at H-relative position. frac_pos/tail are (x,y,z) fractions."""
        head = Vector(frac_pos) * self.H
        t = Vector(tail) * self.H if tail is not None else None
        bone = self.arm.bone(name, head, t, parent, use_deform)
        if role:
            self.expected[role] = name
        return bone

    def abs_b(self, name, pos, parent=None, role=None, use_deform=True):
        bone = self.arm.bone(name, Vector(pos), None, parent, use_deform)
        if role:
            self.expected[role] = name
        return bone


def _add_arm(rig, side, names, has_shoulder=True, twist="none", finger_count=5,
             carpals=False):
    """Build one arm. `names` is a dict with keys:
    shoulder, upper, fore, hand, finger(i,j)->name, plus twist names."""
    H, pose = rig.H, rig.pose
    sgn = 1 if side == "left" else -1
    d = _arm_dir(sgn, pose)
    sh_root = Vector((sgn * P["shoulder_root_x"], 0.0, P["shoulder_z"])) * H
    sh_joint = Vector((sgn * P["shoulder_joint_x"], 0.0, P["shoulder_z"])) * H
    elbow = sh_joint + d * (P["upper_arm_len"] * H)
    wrist = elbow + d * (P["forearm_len"] * H)

    parent = getattr(rig, "arm_parent", None) or rig.chest_bone
    if has_shoulder:
        parent = rig.arm.bone(names["shoulder"], sh_root, sh_joint, parent)
        rig.expected[f"{side}_shoulder_bone"] = parent.name

    if twist == "inchain":
        up_bend = rig.arm.bone(names["upper"], sh_joint, None, parent)
        up_twist = rig.arm.bone(names["upper_twist"], sh_joint + d * (P["upper_arm_len"] * H * 0.5), None, up_bend)
        fore_bend = rig.arm.bone(names["fore"], elbow, None, up_twist)
        fore_twist = rig.arm.bone(names["fore_twist"], elbow + d * (P["forearm_len"] * H * 0.5), None, fore_bend)
        hand = rig.arm.bone(names["hand"], wrist, None, fore_twist)
        rig.expected[f"{side}_upper_arm_bone"] = up_bend.name
        rig.expected[f"{side}_lower_arm_bone"] = fore_bend.name
        rig.expected[f"{side}_hand_bone"] = hand.name
    else:
        up = rig.arm.bone(names["upper"], sh_joint, None, parent)
        fore = rig.arm.bone(names["fore"], elbow, None, up)
        hand = rig.arm.bone(names["hand"], wrist, None, fore)
        rig.expected[f"{side}_upper_arm_bone"] = up.name
        rig.expected[f"{side}_lower_arm_bone"] = fore.name
        rig.expected[f"{side}_hand_bone"] = hand.name
        if twist == "child":
            # XPS foretwist / UE twist bones: leaf children hanging on the segment
            rig.arm.bone(names["upper_twist"], sh_joint + d * (P["upper_arm_len"] * H * 0.55), None, up)
            rig.arm.bone(names["fore_twist"], elbow + d * (P["forearm_len"] * H * 0.55), None, fore)

    # fingers: chains of 3 from the hand (+ optional leading carpal)
    hand_len = P["hand_len"] * H
    palm_dir = d
    # lateral spread inside the palm plane (y axis ~ depth of hand)
    finger_specs = [
        ("thumb", 0.30, Vector((sgn * 0.25, -0.85, -0.45)).normalized()),
        ("index", 0.95, (palm_dir + Vector((0, -0.22, 0))).normalized()),
        ("middle", 1.00, palm_dir),
        ("ring", 0.95, (palm_dir + Vector((0, 0.22, 0))).normalized()),
        ("pinky", 0.85, (palm_dir + Vector((0, 0.42, 0))).normalized()),
    ]
    mmd_idx = {"thumb": ("_0", "_1", "_2"), "index": ("_1", "_2", "_3"),
               "middle": ("_1", "_2", "_3"), "ring": ("_1", "_2", "_3"),
               "pinky": ("_1", "_2", "_3")}
    for fi, (fname, reach, fdir) in enumerate(finger_specs[:finger_count]):
        root = wrist + fdir * (hand_len * (0.35 if fname == "thumb" else reach))
        parent_b = hand
        if carpals and fname != "thumb":
            parent_b = rig.arm.bone(names["carpal"](fi), wrist + fdir * (hand_len * reach * 0.55), None, hand)
        seg = hand_len * (0.30 if fname == "thumb" else 0.24)
        prev = parent_b
        for j in range(3):
            bn = rig.arm.bone(names["finger"](fi, j), root + fdir * (seg * j), None, prev)
            prev = bn
            rig.expected[f"{side}_{fname}{mmd_idx[fname][j]}"] = bn.name


def _add_leg(rig, side, names, has_toe=True, twist="none", parent=None,
             corrective=False, metatarsals=False):
    H = rig.H
    sgn = 1 if side == "left" else -1
    hip = Vector((sgn * P["thigh_x"], 0.0, P["hips_z"])) * H
    knee = Vector((sgn * P["thigh_x"], -0.012, P["knee_z"])) * H
    ankle = Vector((sgn * P["thigh_x"], 0.012, P["ankle_z"])) * H
    toe = ankle + Vector((0, -P["foot_fwd"], -0.02)) * H

    parent = parent or rig.hips_bone
    if corrective:
        # Daz-port style leading corrective bone right next to the hip joint
        # (tifa's c_thigh_b.l) — must NOT be picked as the thigh.
        parent = rig.arm.bone(f"c_thigh_b.{side[0]}",
                              hip + Vector((0, 0.02, 0.015)) * H, None, parent)
    thigh = rig.arm.bone(names["thigh"], hip, None, parent)
    calf_parent = thigh
    if twist == "inchain":
        calf_parent = rig.arm.bone(names["thigh_twist"], hip + (knee - hip) * 0.5,
                                   None, thigh)
    calf = rig.arm.bone(names["calf"], knee, None, calf_parent)
    foot = rig.arm.bone(names["foot"], ankle, toe, calf)
    rig.expected[f"{side}_thigh_bone"] = thigh.name
    rig.expected[f"{side}_calf_bone"] = calf.name
    rig.expected[f"{side}_foot_bone"] = foot.name
    if twist == "child":
        rig.arm.bone(names["thigh_twist"], hip + (knee - hip) * 0.5, None, thigh)
    toe_parent = foot
    if metatarsals:
        # real Daz: lMetatarsals' head is essentially AT the heel/ankle —
        # toe selection must skip it (it'd give 足首 a degenerate direction)
        toe_parent = rig.arm.bone(f"{side[0]}Metatarsals",
                                  ankle + Vector((0, -0.008, -0.012)) * H,
                                  None, foot)
    if has_toe:
        tb = rig.arm.bone(names["toe"], toe, toe + Vector((0, -P["toe_fwd"], 0)) * H,
                          toe_parent)
        rig.expected[f"{side}_toe_bone"] = tb.name


def _add_eyes(rig, names, head_bone):
    H = rig.H
    for side, sgn in (("left", 1), ("right", -1)):
        e = rig.arm.bone(names[side], Vector((sgn * P["eye_x"], P["eye_y"], P["eye_z"])) * H,
                         None, head_bone)
        rig.expected[f"{side}_eye_bone"] = e.name


def _add_chain(rig, base_name, parent, start_frac, step_frac, count):
    """A dangling chain (hair/skirt/tail): `count` bones marching by step."""
    prev = parent
    pos = Vector(start_frac) * rig.H
    step = Vector(step_frac) * rig.H
    for i in range(count):
        prev = rig.arm.bone(f"{base_name} {i + 1}", pos.copy(), None, prev)
        pos += step
    return prev


# ---------------------------------------------------------------------------
# naming tables
# ---------------------------------------------------------------------------

def _xnalara_names(side):
    s = side
    return {
        "shoulder": f"arm {s} shoulder 1", "upper": f"arm {s} shoulder 2",
        "fore": f"arm {s} elbow", "hand": f"arm {s} wrist",
        "upper_twist": f"arm {s} foretwist 1", "fore_twist": f"arm {s} foretwist 2",
        "finger": lambda fi, j: f"arm {s} finger {fi + 1}{'abc'[j]}",
        "carpal": lambda fi: f"arm {s} carpal {fi + 1}",
        "thigh": f"leg {s} thigh", "calf": f"leg {s} knee",
        "foot": f"leg {s} ankle", "toe": f"leg {s} toes",
        "thigh_twist": f"leg {s} thightwist",
    }


def _bip_names(side):
    S = "L" if side == "left" else "R"
    fingers = ["Finger0", "Finger1", "Finger2", "Finger3", "Finger4"]
    return {
        "shoulder": f"Bip001 {S} Clavicle", "upper": f"Bip001 {S} UpperArm",
        "fore": f"Bip001 {S} Forearm", "hand": f"Bip001 {S} Hand",
        "upper_twist": f"Bip001 {S} UpArmTwist", "fore_twist": f"Bip001 {S} ForeTwist",
        "finger": lambda fi, j: f"Bip001 {S} {fingers[fi]}" + ("" if j == 0 else str(j)),
        "carpal": lambda fi: f"Bip001 {S} Carpal{fi}",
        "thigh": f"Bip001 {S} Thigh", "calf": f"Bip001 {S} Calf",
        "foot": f"Bip001 {S} Foot", "toe": f"Bip001 {S} Toe0",
        "thigh_twist": f"Bip001 {S} ThighTwist",
    }


def _ue4_names(side):
    s = "l" if side == "left" else "r"
    fingers = ["thumb", "index", "middle", "ring", "pinky"]
    return {
        "shoulder": f"clavicle_{s}", "upper": f"upperarm_{s}",
        "fore": f"lowerarm_{s}", "hand": f"hand_{s}",
        "upper_twist": f"upperarm_twist_01_{s}", "fore_twist": f"lowerarm_twist_01_{s}",
        "finger": lambda fi, j: f"{fingers[fi]}_{j + 1:02d}_{s}",
        "carpal": lambda fi: f"{fingers[fi]}_metacarpal_{s}",
        "thigh": f"thigh_{s}", "calf": f"calf_{s}",
        "foot": f"foot_{s}", "toe": f"ball_{s}",
        "thigh_twist": f"thigh_twist_01_{s}",
    }


def _daz_names(side):
    s = "l" if side == "left" else "r"
    fingers = ["Thumb", "Index", "Mid", "Ring", "Pinky"]
    return {
        "shoulder": f"{s}Collar", "upper": f"{s}ShldrBend",
        "fore": f"{s}ForearmBend", "hand": f"{s}Hand",
        "upper_twist": f"{s}ShldrTwist", "fore_twist": f"{s}ForearmTwist",
        "finger": lambda fi, j: f"{s}{fingers[fi]}{j + 1}",
        "carpal": lambda fi: f"{s}Carpal{fi}",
        "thigh": f"{s}ThighBend", "calf": f"{s}Shin",
        "foot": f"{s}Foot", "toe": f"{s}Toe",
        "thigh_twist": f"{s}ThighTwist",
    }


# ---------------------------------------------------------------------------
# full-rig builders
# ---------------------------------------------------------------------------

def build_rig(naming="xnalara", height=1.7, pose="A", spine_segments=2,
              has_shoulder=True, has_toe=True, arm_twist="none", leg_twist="none",
              finger_count=5, carpals=False, skirt=0, hair=0, wings=False,
              breast=False, unused_helpers=False, legs_from_pelvis=False,
              arm_ribbon=False, proportions=None,
              leg_corrective=False, leg_metatarsals=False, arms_from_neck=False):
    """Build a complete synthetic humanoid. Returns (FakeArmatureData, expected).

    `proportions` overrides entries of the P table for this build (e.g. a
    short clavicle reproducing real-rig geometry that fooled joint scoring).
    """
    saved_P = None
    if proportions:
        saved_P = dict(P)
        P.update(proportions)
    try:
        return _build_rig_inner(naming, height, pose, spine_segments,
                                has_shoulder, has_toe, arm_twist, leg_twist,
                                finger_count, carpals, skirt, hair, wings,
                                breast, unused_helpers, legs_from_pelvis,
                                arm_ribbon, leg_corrective, leg_metatarsals,
                                arms_from_neck)
    finally:
        if saved_P is not None:
            P.clear()
            P.update(saved_P)


def _build_rig_inner(naming, height, pose, spine_segments, has_shoulder,
                     has_toe, arm_twist, leg_twist, finger_count, carpals,
                     skirt, hair, wings, breast, unused_helpers,
                     legs_from_pelvis, arm_ribbon, leg_corrective=False,
                     leg_metatarsals=False, arms_from_neck=False):
    rig = Rig(height, pose)
    name_fn = {"xnalara": _xnalara_names, "bip001": _bip_names,
               "ue4": _ue4_names, "daz": _daz_names}.get(naming)

    # --- core column -------------------------------------------------------
    if naming == "xnalara":
        root = rig.b("root ground", (0, 0, 0), role="all_parents_bone")
        hips = rig.b("root hips", (0, 0, P["hips_z"]), root, role="lower_body_bone")
        spine_names = ["spine lower", "spine middle", "spine upper", "spine 4", "spine 5", "spine 6"]
        neck_name, head_name = "head neck lower", "head neck upper"
    elif naming == "bip001":
        root = rig.b("Bip001", (0, 0, 0), role="all_parents_bone")
        hips = rig.b("Bip001 Pelvis", (0, 0, P["hips_z"]), root, role="lower_body_bone")
        spine_names = ["Bip001 Spine", "Bip001 Spine1", "Bip001 Spine2", "Bip001 Spine3", "Bip001 Spine4", "Bip001 Spine5"]
        neck_name, head_name = "Bip001 Neck", "Bip001 Head"
    elif naming == "ue4":
        root = rig.b("root", (0, 0, 0), role="all_parents_bone")
        hips = rig.b("pelvis", (0, 0, P["hips_z"]), root, role="lower_body_bone")
        spine_names = ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "spine_06"]
        neck_name, head_name = "neck_01", "head"
    elif naming == "daz":
        hips = rig.b("hip", (0, 0, P["hips_z"]), role="lower_body_bone")
        root = hips
        spine_names = ["abdomenLower", "abdomenUpper", "chestLower", "chestUpper", "spine5", "spine6"]
        neck_name, head_name = "neckLower", "head"
    elif naming == "garbage":
        root = rig.b("bone_000", (0, 0, 0), role="all_parents_bone")
        hips = rig.b("bone_001", (0, 0, P["hips_z"]), root, role="lower_body_bone")
        spine_names = [f"bone_01{i}" for i in range(6)]
        neck_name, head_name = "bone_020", "bone_021"
        import itertools
        _ctr = itertools.count(100)
        name_fn = lambda side: {  # noqa: E731
            k: (lambda fi, j, c=_ctr: f"bone_{next(c):03d}") if k == "finger"
            else (lambda fi, c=_ctr: f"bone_{next(c):03d}") if k == "carpal"
            else f"bone_{next(_ctr):03d}"
            for k in ("shoulder", "upper", "fore", "hand", "upper_twist", "fore_twist",
                      "finger", "carpal", "thigh", "calf", "foot", "toe", "thigh_twist")
        }
    else:
        raise ValueError(naming)

    rig.hips_bone = hips

    # spine chain hips→chest
    zs = {2: [P["waist_z"], P["chest2_z"]],
          3: [P["waist_z"], P["chest_z"], P["chest2_z"]],
          4: [0.58, 0.65, 0.72, P["chest2_z"]],
          5: [0.57, 0.63, 0.69, 0.74, P["chest2_z"]],
          6: [0.56, 0.61, 0.66, 0.71, 0.75, P["chest2_z"]]}[spine_segments]
    prev = hips
    spine_bones = []
    for i, z in enumerate(zs):
        prev = rig.b(spine_names[i], (0, 0.01, z), prev)
        spine_bones.append(prev)
    rig.expected["upper_body_bone"] = spine_bones[0].name
    rig.expected["upper_body2_bone"] = spine_bones[-1].name
    rig.chest_bone = spine_bones[-1]

    neck = rig.b(neck_name, (0, 0, P["neck_z"]), rig.chest_bone, role="neck_bone")
    head = rig.b(head_name, (0, 0, P["head_z"]), neck, role="head_bone")
    rig.arm_parent = neck if arms_from_neck else None

    # --- limbs --------------------------------------------------------------
    leg_parent = hips
    if legs_from_pelvis:
        leg_parent = rig.b("pelvis helper", (0, 0, P["hips_z"] - 0.01), hips)
    for side in ("left", "right"):
        nm = name_fn(side)
        _add_arm(rig, side, nm, has_shoulder, arm_twist, finger_count, carpals)
        _add_leg(rig, side, nm, has_toe, leg_twist, parent=leg_parent,
                 corrective=leg_corrective, metatarsals=leg_metatarsals)

    # eyes (+ decoy symmetric pairs on the head)
    eye_names = {"xnalara": {"left": "head eyeball left", "right": "head eyeball right"},
                 "bip001": {"left": "Bip001 L Eye", "right": "Bip001 R Eye"},
                 "ue4": {"left": "eye_l", "right": "eye_r"},
                 "daz": {"left": "lEye", "right": "rEye"},
                 "garbage": {"left": "bone_090", "right": "bone_091"}}[naming]
    _add_eyes(rig, eye_names, head)

    # --- decoration ---------------------------------------------------------
    if hair:
        for i, sgn in enumerate([1, -1, 1, -1][:hair]):
            _add_chain(rig, f"hair chain {i}", head,
                       (sgn * 0.04, 0.04, 0.97), (sgn * 0.01, 0.02, -0.045), 5)
    if skirt:
        for i in range(skirt):
            ang = 2 * math.pi * i / skirt
            x, y = 0.07 * math.sin(ang), 0.05 * math.cos(ang)
            _add_chain(rig, f"skirt chain {i}", hips,
                       (x, y, P["hips_z"] - 0.02), (x * 0.3, y * 0.3, -0.055), 4)
    if wings:
        for sgn, side in ((1, "left"), (-1, "right")):
            _add_chain(rig, f"wing {side}", rig.chest_bone,
                       (sgn * 0.03, 0.05, 0.78), (sgn * 0.07, 0.045, 0.02), 4)
    if breast:
        for sgn, side in ((1, "left"), (-1, "right")):
            b1 = rig.b(f"boob {side} 1", (sgn * 0.05, -0.05, 0.74), rig.chest_bone)
            rig.b(f"boob {side} 2", (sgn * 0.055, -0.09, 0.735), b1)
    if arm_ribbon:
        # sleeve ribbon: rooted right next to the forearm but hanging DOWN
        # off the arm — physics strand, must NOT be folded as twist.
        for sgn, side in ((1, "left"), (-1, "right")):
            d = _arm_dir(sgn, pose)
            elbow = (Vector((sgn * P["shoulder_joint_x"], 0, P["shoulder_z"]))
                     + d * P["upper_arm_len"]) * 1.0
            start = (elbow + d * (P["forearm_len"] * 0.4))
            rig.abs_b(f"ribbon {side} 1", Vector(start) * rig.H,
                      rig.arm.bones[name_fn(side)["fore"]])
            prev = rig.arm.bones[f"ribbon {side} 1"]
            pos = Vector(start) * rig.H
            for i in range(2, 5):
                pos = pos + Vector((0, 0.012, -0.05)) * rig.H
                prev = rig.arm.bone(f"ribbon {side} {i}", pos.copy(), None, prev)

    if unused_helpers:
        # XPS-style 'unused' bones: pelvis helper + deltoid caps on the upper arms
        rig.b("unused pelvis lasso", (0, 0.02, P["hips_z"] - 0.03), hips)
        for side, sgn in (("left", 1), ("right", -1)):
            d = _arm_dir(sgn, pose)
            sh = Vector((sgn * P["shoulder_joint_x"], 0, P["shoulder_z"])) * rig.H
            cap = sh + d * (P["upper_arm_len"] * rig.H * 0.18) + Vector((0, 0, 0.012)) * rig.H
            up = rig.arm.bone(f"unused {side} xtra07", Vector(cap), None,
                              rig.arm.bones[name_fn(side)["upper"]])
            rig.arm.bone(f"unused {side} xtra07pp", Vector(cap) + Vector((0, 0, 0.008)) * rig.H,
                         None, up)

    return rig.arm, rig.expected


# canonical test matrix: (case_name, build_rig kwargs)
CASES = [
    ("xnalara_basic", dict(naming="xnalara", breast=True, unused_helpers=True)),
    ("xnalara_raw_scale", dict(naming="xnalara", height=17.0, breast=True)),
    ("xnalara_tiny", dict(naming="xnalara", height=0.17)),
    ("xnalara_skirt_hair", dict(naming="xnalara", skirt=6, hair=4, breast=True)),
    ("xnalara_no_toe", dict(naming="xnalara", has_toe=False)),
    ("xnalara_child_twist", dict(naming="xnalara", arm_twist="child", leg_twist="child")),
    ("bip001_tpose", dict(naming="bip001", pose="T", spine_segments=3)),
    ("bip001_spine4", dict(naming="bip001", spine_segments=4)),
    ("ue4_twist", dict(naming="ue4", arm_twist="child", leg_twist="child", spine_segments=3, pose="A")),
    ("daz_inchain_T", dict(naming="daz", arm_twist="inchain", pose="T", spine_segments=4, carpals=False)),
    ("garbage_names", dict(naming="garbage", spine_segments=3)),
    ("no_shoulder", dict(naming="ue4", has_shoulder=False, spine_segments=3)),
    ("four_finger", dict(naming="xnalara", finger_count=4)),
    ("spine6_wings", dict(naming="ue4", spine_segments=6, wings=True)),
    # real-rig regression (inase): short clavicle + short steep arm — joint
    # scoring once picked (clavicle, elbow) as (upper, elbow) here; 4-node
    # chains must map positionally.
    ("short_clavicle", dict(naming="xnalara", proportions={
        "shoulder_root_x": 0.042, "upper_arm_len": 0.123, "forearm_len": 0.127})),
    # real-rig regression (tifa): Daz-port leg with a leading corrective bone
    # and a metatarsal chain — thigh must be the bend bone, not c_thigh_b.*
    ("daz_leg_corrective", dict(naming="daz", arm_twist="inchain", pose="T",
                                spine_segments=4, leg_corrective=True,
                                leg_metatarsals=True)),
    ("daz_leg_inchain_twist", dict(naming="daz", spine_segments=4,
                                   leg_twist="inchain", leg_metatarsals=True)),
    # real-rig regression (tifa): both thighs hang off a CENTERED pelvis bone
    # under the hips — the fork must be promoted through it on both sides.
    ("daz_pelvis_passthrough", dict(naming="daz", legs_from_pelvis=True,
                                    leg_corrective=True, leg_metatarsals=True,
                                    spine_segments=4)),
    # real-rig regression (rouffe): shoulders hang off the NECK root with
    # near-centered clavicle roots — fork scan must reach the second-to-last
    # chain bone and remap chest/neck semantics.
    ("xnalara_neck_shoulders", dict(naming="xnalara", arms_from_neck=True,
                                    spine_segments=3,
                                    proportions={"shoulder_root_x": 0.004})),
]
