"""Offline weight-pipeline test — runs the REAL transfer/twist/palm code on a
synthetic skinned arm (no Blender needed).

    python3 test/offline/run_weight_tests.py [-v]

Scenario A (UE-style port): the arm mesh is partially skinned to side-child
twist helper bones (upperarm_twist_01_l / lowerarm_twist_01_l). The fold step
must consume them into the 腕/ひじ pools so the τ twist split grades them —
this is exactly the candy-wrap dead-bone gap for arbitrary XPS ports.

Scenario B (XNALara default): no twist helpers; the distal forearm is skinned
to the hand bone (XPS habit). The twist split's reclaim must still feed 手捩.

Assertions throughout: per-vertex weight totals conserved, twist gradient
monotone along the limb, no weight left on consumed helpers, palm synthesis
conserving.
"""

import os
import sys
import math
import types
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fake_bpy  # noqa: E402
from fakes import FakeArmatureData  # noqa: E402  (loaded for type access)
from mathutils import Vector  # noqa: E402
import synth  # noqa: E402

VERBOSE = "-v" in sys.argv
_failures = []


def check(desc, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  {mark}  {desc}" + (f"  {detail}" if (detail and (VERBOSE or not cond)) else ""))
    if not cond:
        _failures.append(desc)


# ---------------------------------------------------------------------------
# package loading (real addon modules, fake bpy)
# ---------------------------------------------------------------------------

def _stub_pkg(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [path]
    sys.modules[name] = mod
    return mod


def load_addon_modules(arm_obj, meshes):
    fake_bpy.install([arm_obj] + meshes)
    for name in [n for n in list(sys.modules) if n == "cmmd" or n.startswith("cmmd.")]:
        del sys.modules[name]
    _stub_pkg("cmmd", ROOT)
    _stub_pkg("cmmd.convert", os.path.join(ROOT, "convert"))
    _stub_pkg("cmmd.convert.weights", os.path.join(ROOT, "convert", "weights"))
    mods = {}
    for sub in ("skeleton_identifier", "helper_classifier"):
        mods[sub] = importlib.import_module(f"cmmd.{sub}")
    for sub in ("common", "fold", "transfer", "twist", "palm", "sanitize"):
        mods[sub] = importlib.import_module(f"cmmd.convert.weights.{sub}")
    return mods


# ---------------------------------------------------------------------------
# scenario construction
# ---------------------------------------------------------------------------

MMD_ARM_RENAMES = {
    "left_shoulder_bone": "左肩", "right_shoulder_bone": "右肩",
    "left_upper_arm_bone": "左腕", "right_upper_arm_bone": "右腕",
    "left_lower_arm_bone": "左ひじ", "right_lower_arm_bone": "右ひじ",
    "left_hand_bone": "左手首", "right_hand_bone": "右手首",
    "left_thumb_0": "左親指０", "left_thumb_1": "左親指１", "left_thumb_2": "左親指２",
    "left_index_1": "左人指１", "left_middle_1": "左中指１",
    "left_ring_1": "左薬指１", "left_pinky_1": "左小指１",
    "upper_body_bone": "上半身", "upper_body2_bone": "上半身2",
    "neck_bone": "首", "head_bone": "頭",
    "left_thigh_bone": "左足", "right_thigh_bone": "右足",
    "left_calf_bone": "左ひざ", "right_calf_bone": "右ひざ",
    "left_foot_bone": "左足首", "right_foot_bone": "右足首",
    "left_toe_bone": "左足先EX", "right_toe_bone": "右足先EX",
}


def rename_bone(arm_data, old, new):
    b = arm_data.bones.get(old)
    if b is None or old == new:
        return
    coll = arm_data.bones
    del coll._by_name[old]
    b.name = new
    coll._by_name[new] = b


def simulate_rename(arm_data, expected):
    """Apply the rename step using the synthetic ground-truth mapping."""
    for role, mmd_name in MMD_ARM_RENAMES.items():
        src = expected.get(role)
        if src:
            rename_bone(arm_data, src, mmd_name)


def perp_frame(d):
    up = Vector((0, 1, 0)) if abs(d.dot(Vector((0, 1, 0)))) < 0.9 else Vector((0, 0, 1))
    n1 = d.cross(up).normalized()
    n2 = d.cross(n1).normalized()
    return n1, n2


def tube_verts(mesh, a, b, stations, ring=6, radius=0.03):
    """Add rings of vertices along segment a→b; returns list of (t, [verts])."""
    d = (b - a).normalized()
    n1, n2 = perp_frame(d)
    out = []
    for t in stations:
        p = a + (b - a) * t
        ring_verts = []
        for k in range(ring):
            ang = 2 * math.pi * k / ring
            co = p + n1 * (radius * math.cos(ang)) + n2 * (radius * math.sin(ang))
            ring_verts.append(mesh.add_vertex(co))
        out.append((t, ring_verts))
    return out


def vertex_total(v):
    return sum(e.weight for e in v.groups)


def group_weight(mesh, v, name):
    vg = mesh.vertex_groups.get(name)
    if not vg:
        return 0.0
    return sum(e.weight for e in v.groups if e.group == vg.index)


def build_scenario(naming, arm_twist, distal_to_hand):
    """Build rig + skinned left-arm tube. Returns (arm_obj, mesh, markers)."""
    arm_data, expected = synth.build_rig(
        naming=naming, arm_twist=arm_twist,
        leg_twist="none", spine_segments=3)
    simulate_rename(arm_data, expected)

    bones = arm_data.bones
    sh = bones["左腕"].head_local
    el = bones["左ひじ"].head_local
    wr = bones["左手首"].head_local
    mid1 = bones["左中指１"].head_local
    # simulate `complete`: limb tails point at the next joint
    bones["左腕"].tail_local = el.copy()
    bones["左ひじ"].tail_local = wr.copy()
    bones["左手首"].tail_local = mid1.copy()

    arm_obj = fake_bpy.FakeArmatureObject(arm_data)
    mesh = fake_bpy.FakeMeshObject("body", arm_obj)

    markers = {}
    stations = [i / 9 for i in range(10)]

    twist_names = {"child": ("upperarm_twist_01_l", "lowerarm_twist_01_l"),
                   "inchain": ("lShldrTwist", "lForearmTwist")}.get(arm_twist)

    upper = tube_verts(mesh, sh, el, stations)
    for t, ring in upper:
        for v in ring:
            if twist_names:
                tw = 0.6 * t
                mesh.set_weight(v.index, twist_names[0], tw)
                mesh.set_weight(v.index, "左腕", 1.0 - tw)
            else:
                mesh.set_weight(v.index, "左腕", 1.0)
    markers["upper"] = upper

    fore = tube_verts(mesh, el, wr, stations)
    for t, ring in fore:
        for v in ring:
            if twist_names:
                tw = 0.7 * t
                mesh.set_weight(v.index, twist_names[1], tw)
                mesh.set_weight(v.index, "左ひじ", 1.0 - tw)
            elif distal_to_hand:
                hand_w = max(0.0, (t - 0.6) / 0.4) * 0.9
                mesh.set_weight(v.index, "左ひじ", 1.0 - hand_w)
                if hand_w > 0:
                    mesh.set_weight(v.index, "左手首", hand_w)
            else:
                mesh.set_weight(v.index, "左ひじ", 1.0)
    markers["fore"] = fore

    palm = tube_verts(mesh, wr, mid1, [0.25, 0.5, 0.75], ring=6, radius=0.02)
    for t, ring in palm:
        for v in ring:
            mesh.set_weight(v.index, "左手首", 1.0)
    markers["palm"] = palm

    # thumb-bleed verts: behind the thumb base on the inner wrist (u < -0.1
    # along 親指０→親指１), weighted half to 親指０ — the XPS over-wide bind.
    t0 = bones["左親指０"].head_local
    t1 = bones["左親指１"].head_local
    tdir = (t1 - t0).normalized()
    bleed = []
    for k in (-0.35, -0.55):
        v = mesh.add_vertex(t0 + tdir * ((t1 - t0).length * k))
        mesh.set_weight(v.index, "左親指０", 0.5)
        mesh.set_weight(v.index, "左手首", 0.5)
        bleed.append(v)
    markers["bleed"] = bleed

    return arm_obj, mesh, markers


def add_metacarpals(arm_data):
    """Simulate `complete`: create 指０ bones between 手首 and 指１."""
    bones = arm_data.bones
    wr = bones.get("左手首")
    for f in ("人指", "中指", "薬指", "小指"):
        f1 = bones.get(f"左{f}１")
        if wr and f1 and not bones.get(f"左{f}０"):
            arm_data.bone(f"左{f}０", (wr.head_local + f1.head_local) * 0.5,
                          f1.head_local.copy(), wr)


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------

def run_scenario_A():
    print("\nScenario A — UE 式侧挂 twist 辅助骨 (fold → τ 切分):")
    arm_obj, mesh, markers = build_scenario("ue4", "child", distal_to_hand=False)
    mods = load_addon_modules(arm_obj, [mesh])

    totals_before = [vertex_total(v) for v in mesh.data.vertices]

    op = mods["transfer"].OBJECT_OT_transfer_unused_weights()
    result = op.execute(fake_bpy.FakeContext(arm_obj))
    check("transfer 执行成功", result == {'FINISHED'})
    check("twist 辅助组已被消费",
          "upperarm_twist_01_l" not in mesh.vertex_groups
          and "lowerarm_twist_01_l" not in mesh.vertex_groups)

    distal_up = markers["upper"][-1][1][0]
    check("上臂远端权重折入 腕 池",
          abs(group_weight(mesh, distal_up, "左腕") - 1.0) < 1e-6,
          f"腕={group_weight(mesh, distal_up, '左腕'):.3f}")

    totals_mid = [vertex_total(v) for v in mesh.data.vertices]
    drift = max(abs(a - b) for a, b in zip(totals_before, totals_mid))
    check("fold 后逐顶点权重守恒", drift < 1e-6, f"max drift={drift:.2e}")

    mods["twist"].split_twist_weights(arm_obj)

    totals_after = [vertex_total(v) for v in mesh.data.vertices]
    drift = max(abs(a - b) for a, b in zip(totals_before, totals_after))
    check("τ 切分后逐顶点权重守恒", drift < 1e-6, f"max drift={drift:.2e}")

    # THE generalisation assertion: distal upper-arm vertices (whose weight
    # used to live on the dead UE twist bone) now carry 腕捩-family weight.
    fam = ("左腕捩", "左腕捩1", "左腕捩2", "左腕捩3")
    tw_w = sum(group_weight(mesh, distal_up, n) for n in fam)
    check("上臂远端获得 腕捩 系权重 (糖纸修复)", tw_w > 0.5, f"腕捩系={tw_w:.3f}")

    near_el = markers["fore"][1][1][0]  # forearm t≈0.11 < TAU_LO_FOREARM
    h1 = group_weight(mesh, near_el, "左手捩1")
    check("肘邻接段无 手捩1 渗漏", h1 < 1e-6, f"手捩1={h1:.4f}")

    distal_fore = markers["fore"][-1][1][0]
    hfam = sum(group_weight(mesh, distal_fore, n)
               for n in ("左手捩", "左手捩1", "左手捩2", "左手捩3"))
    check("前臂远端获得 手捩 系权重", hfam > 0.5, f"手捩系={hfam:.3f}")

    # monotone twist gradient along the forearm
    fracs = []
    for t, ring in markers["fore"]:
        v = ring[0]
        tot = vertex_total(v) or 1.0
        fr = sum(group_weight(mesh, v, n)
                 for n in ("左手捩", "左手捩1", "左手捩2", "左手捩3")) / tot
        fracs.append(fr)
    monotone = all(b >= a - 1e-9 for a, b in zip(fracs, fracs[1:]))
    check("手捩占比沿前臂单调", monotone,
          "fracs=" + "/".join(f"{f:.2f}" for f in fracs))

    # palm synthesis
    add_metacarpals(arm_obj.data)
    n_deb = mods["palm"].debleed_thumb_to_wrist(arm_obj)
    n_pal = mods["palm"].redistribute_palm_to_metacarpals(arm_obj)
    check("拇指 debleed 命中渗出顶点", n_deb >= len(markers["bleed"]), f"n={n_deb}")
    check("掌部重分配执行", n_pal > 0, f"n={n_pal}")

    # ramp check: the u=-0.35 vertex sits mid-ramp (partial clear by design),
    # the u=-0.55 vertex is past THUMB_U_LO (full clear).
    v_mid, v_deep = markers["bleed"]
    w_mid = group_weight(mesh, v_mid, "左親指０")
    w_deep = group_weight(mesh, v_deep, "左親指０")
    check("渗出顶点 親指０ 按斜坡清退", w_deep < 0.01 and 0.0 < w_mid < 0.25,
          f"深处={w_deep:.3f} 中段={w_mid:.3f}")

    mid_palm = markers["palm"][1][1][0]
    meta = sum(group_weight(mesh, mid_palm, f"左{f}０")
               for f in ("人指", "中指", "薬指", "小指"))
    check("掌中部权重分到掌骨", meta > 0.3, f"指０系={meta:.3f}")

    totals_final = [vertex_total(v) for v in mesh.data.vertices]
    drift = max(abs(a - b) for a, b in zip(totals_before, totals_final))
    check("全链路逐顶点权重守恒", drift < 1e-6, f"max drift={drift:.2e}")

    # --- sanitize: craft a worst-case vertex (5 real + 2 dust groups) -------
    v_bad = markers["fore"][5][1][1]
    mesh.set_weight(v_bad.index, "左肩", 0.001)       # dust
    mesh.set_weight(v_bad.index, "上半身", 0.002)     # dust
    mesh.set_weight(v_bad.index, "左手首", 0.3)       # 5th real contributor
    nv, nc = mods["sanitize"].sanitize_weights(arm_obj)
    check("sanitize 执行", nv > 0, f"touched={nv} culled={nc}")

    bone_names = {b.name for b in arm_obj.data.bones}
    ok_counts = True
    ok_norm = True
    for v in mesh.data.vertices:
        deform = [e for e in v.groups
                  if mesh.vertex_groups._list[e.group].name in bone_names and e.weight > 0]
        if len(deform) > 4:
            ok_counts = False
        tot = sum(e.weight for e in deform)
        if deform and abs(tot - 1.0) > 1e-4:
            ok_norm = False
    check("sanitize 后每顶点≤4骨", ok_counts)
    check("sanitize 后逐顶点归一化", ok_norm)
    dust = group_weight(mesh, v_bad, "左肩") + group_weight(mesh, v_bad, "上半身")
    check("残渣权重已剔除", dust == 0.0, f"dust={dust:.4f}")


def run_scenario_C():
    print("\nScenario C — Daz 式链内 twist 骨 (lShldrTwist 在主链内):")
    arm_obj, mesh, markers = build_scenario("daz", "inchain", distal_to_hand=False)
    mods = load_addon_modules(arm_obj, [mesh])

    totals_before = [vertex_total(v) for v in mesh.data.vertices]

    op = mods["transfer"].OBJECT_OT_transfer_unused_weights()
    op.execute(fake_bpy.FakeContext(arm_obj))
    check("链内 twist 组已被消费",
          "lShldrTwist" not in mesh.vertex_groups
          and "lForearmTwist" not in mesh.vertex_groups)
    check("链内 twist 骨本体仍在 (层级未破坏)",
          arm_obj.data.bones.get("lShldrTwist") is not None)

    mods["twist"].split_twist_weights(arm_obj)

    distal_up = markers["upper"][-1][1][0]
    fam = ("左腕捩", "左腕捩1", "左腕捩2", "左腕捩3")
    tw_w = sum(group_weight(mesh, distal_up, n) for n in fam)
    check("上臂远端获得 腕捩 系权重", tw_w > 0.5, f"腕捩系={tw_w:.3f}")

    totals_after = [vertex_total(v) for v in mesh.data.vertices]
    drift = max(abs(a - b) for a, b in zip(totals_before, totals_after))
    check("守恒", drift < 1e-6, f"max drift={drift:.2e}")


def run_scenario_B():
    print("\nScenario B — XNALara 默认 (无 twist 骨, 远端前臂绑 手首 → reclaim):")
    arm_obj, mesh, markers = build_scenario("xnalara", "none", distal_to_hand=True)
    mods = load_addon_modules(arm_obj, [mesh])

    totals_before = [vertex_total(v) for v in mesh.data.vertices]

    op = mods["transfer"].OBJECT_OT_transfer_unused_weights()
    op.execute(fake_bpy.FakeContext(arm_obj))
    mods["twist"].split_twist_weights(arm_obj)

    distal_fore = markers["fore"][-2][1][0]  # t≈0.89, inside reclaim ramp
    hfam = sum(group_weight(mesh, distal_fore, n)
               for n in ("左手捩", "左手捩1", "左手捩2", "左手捩3"))
    check("reclaim: 手首 在前臂的权重折入 手捩 系", hfam > 0.3, f"手捩系={hfam:.3f}")

    palm_v = markers["palm"][1][1][0]
    check("掌部 手首 权重未被 reclaim 误伤",
          abs(group_weight(mesh, palm_v, "左手首") - 1.0) < 1e-6)

    totals_after = [vertex_total(v) for v in mesh.data.vertices]
    drift = max(abs(a - b) for a, b in zip(totals_before, totals_after))
    check("守恒", drift < 1e-6, f"max drift={drift:.2e}")


def main():
    run_scenario_A()
    run_scenario_B()
    run_scenario_C()
    print(f"\n{'ALL PASS' if not _failures else f'{len(_failures)} FAILURES: {_failures}'}")
    sys.exit(0 if not _failures else 1)


if __name__ == "__main__":
    main()
