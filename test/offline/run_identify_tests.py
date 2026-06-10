"""Offline identification test matrix — drives the REAL skeleton_identifier /
helper_classifier with synthetic rigs (no Blender needed).

    python3 test/offline/run_identify_tests.py [-v]

Prints one line per case: roles correct / roles expected, plus mismatches.
Exit code 0 only if every case passes fully (used as the refactor gate).
"""

import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)  # mathutils stub + fakes/synth


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(ROOT, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


si = _load("skeleton_identifier", "skeleton_identifier.py")
hc = _load("helper_classifier", "helper_classifier.py")

from synth import CASES, build_rig  # noqa: E402

# roles every humanoid case must get right (when present in expected)
CORE_ROLES = [
    "center_bone", "upper_body_bone", "upper_body2_bone", "neck_bone", "head_bone",
    "left_shoulder_bone", "right_shoulder_bone",
    "left_upper_arm_bone", "right_upper_arm_bone",
    "left_lower_arm_bone", "right_lower_arm_bone",
    "left_hand_bone", "right_hand_bone",
    "left_thigh_bone", "right_thigh_bone",
    "left_calf_bone", "right_calf_bone",
    "left_foot_bone", "right_foot_bone",
    "left_toe_bone", "right_toe_bone",
    "left_eye_bone", "right_eye_bone",
    "left_thumb_0", "left_index_1", "left_middle_1", "left_ring_1", "left_pinky_1",
    "right_thumb_0", "right_index_1",
]


def run_case(name, kwargs, verbose=False):
    arm, expected = build_rig(**kwargs)
    si.clear_cache()
    got = si.identify_skeleton(arm)

    wrong = []
    n_expected = 0
    for role in CORE_ROLES:
        want = expected.get(role)
        if not want:
            continue
        n_expected += 1
        if got.get(role) != want:
            wrong.append((role, got.get(role) or "(empty)", want))
    ok = n_expected - len(wrong)
    status = "PASS" if not wrong else "FAIL"
    print(f"  {status}  {name:<24} {ok:>2}/{n_expected}")
    if wrong and verbose:
        for role, g, w in wrong:
            print(f"          {role:<24} got={g!r:<32} want={w!r}")
    return not wrong, got, arm, expected


def classifier_checks(verbose=False):
    """Helper classification sanity on decorated rigs."""
    print("\nhelper_classifier checks:")
    failures = []

    arm, expected = build_rig(naming="xnalara", skirt=6, hair=4, breast=True,
                              unused_helpers=True, arm_twist="child", leg_twist="child")
    si.clear_cache()
    smap = si.identify_skeleton(arm)
    cls = hc.classify_helpers(arm, smap)

    def check(desc, names, want):
        bad = {n: cls.get(n) for n in names if cls.get(n) not in want}
        mark = "PASS" if not bad else "FAIL"
        print(f"  {mark}  {desc:<38} {('-> ' + str(bad)) if bad else ''}")
        if bad:
            failures.append(desc)

    check("skirt chains preserved (physics)",
          [b.name for b in arm.bones if b.name.startswith("skirt")], {"preserve"})
    check("hair chains preserved (physics)",
          [b.name for b in arm.bones if b.name.startswith("hair")], {"preserve", "other"})
    check("breast bones preserved (physics)",
          [b.name for b in arm.bones if b.name.startswith("boob")], {"preserve"})
    check("arm twist helpers -> twist",
          [b.name for b in arm.bones if "foretwist" in b.name], {"twist"})
    check("deltoid caps -> twist",
          [b.name for b in arm.bones if "xtra07" in b.name], {"twist"})
    check("thigh twist helpers -> preserve/twist",
          [b.name for b in arm.bones if "thightwist" in b.name], {"preserve", "twist"})

    # sleeve ribbon: roots next to the forearm but hanging away — must be a
    # physics strand, NOT a foldable twist helper
    arm2, _ = build_rig(naming="ue4", arm_twist="child", arm_ribbon=True,
                        spine_segments=3)
    si.clear_cache()
    smap2 = si.identify_skeleton(arm2)
    cls2 = hc.classify_helpers(arm2, smap2)

    def check2(desc, names, want):
        bad = {n: cls2.get(n) for n in names if cls2.get(n) not in want}
        mark = "PASS" if not bad else "FAIL"
        print(f"  {mark}  {desc:<38} {('-> ' + str(bad)) if bad else ''}")
        if bad:
            failures.append(desc)

    check2("forearm ribbons preserved (physics)",
           [b.name for b in arm2.bones if b.name.startswith("ribbon")], {"preserve"})
    check2("UE twist children still foldable",
           [b.name for b in arm2.bones if "twist_01" in b.name and "thigh" not in b.name],
           {"twist"})
    return failures


def main():
    verbose = "-v" in sys.argv
    print("identification matrix:")
    fails = []
    for name, kwargs in CASES:
        try:
            ok, *_ = run_case(name, kwargs, verbose)
        except Exception as e:
            ok = False
            print(f"  ERR   {name:<24} {type(e).__name__}: {e}")
        if not ok:
            fails.append(name)

    cfails = classifier_checks(verbose)

    print(f"\n{len(CASES) - len(fails)}/{len(CASES)} identification cases pass; "
          f"classifier failures: {len(cfails)}")
    sys.exit(0 if not fails and not cfails else 1)


if __name__ == "__main__":
    main()
