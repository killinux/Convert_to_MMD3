"""Offline tests for the `complete` step — missing-bone synthesis & per-side
degradation on the REAL convert/complete.py (no Blender needed).

    python3 test/offline/run_complete_tests.py
"""

import os
import sys
import types
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fake_bpy  # noqa: E402
import synth  # noqa: E402
from run_weight_tests import (  # noqa: E402
    MMD_ARM_RENAMES, simulate_rename, rename_bone,  # noqa: F401
)

_failures = []


def check(desc, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  {mark}  {desc}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        _failures.append(desc)


def _stub_pkg(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [path]
    sys.modules[name] = mod
    return mod


def load_complete(arm_obj, meshes=()):
    fake_bpy.install([arm_obj] + list(meshes))
    for name in [n for n in list(sys.modules) if n == "cmmd" or n.startswith("cmmd.")]:
        del sys.modules[name]
    _stub_pkg("cmmd", ROOT)
    _stub_pkg("cmmd.convert", os.path.join(ROOT, "convert"))
    _stub_pkg("cmmd.convert.weights", os.path.join(ROOT, "convert", "weights"))
    return importlib.import_module("cmmd.convert.complete")


def build(naming="xnalara", drop_roles=(), **kwargs):
    arm_data, expected = synth.build_rig(naming=naming, **kwargs)
    expected = {k: v for k, v in expected.items() if k not in drop_roles}
    simulate_rename(arm_data, expected)
    return arm_data, expected


def run_complete(arm_data):
    arm_obj = fake_bpy.FakeArmatureObject(arm_data)
    complete = load_complete(arm_obj)
    op = complete.OBJECT_OT_complete_missing_bones()
    ctx = fake_bpy.FakeContext(arm_obj)
    ctx.mode = 'OBJECT'
    result = op.execute(ctx)
    return result, arm_obj


def case_full():
    print("\ncomplete: 完整 xnalara 骨架")
    arm_data, _ = build(spine_segments=2)
    result, arm_obj = run_complete(arm_data)
    eb = arm_obj.data.bones
    check("执行成功", result == {'FINISHED'})
    for n in ("全ての親", "センター", "グルーブ", "腰", "上半身", "下半身",
              "上半身1", "首1", "左人指０", "左中指０", "腰キャンセル.L", "左足先EX"):
        check(f"{n} 已建", eb.get(n) is not None)
    if eb.get("左腕") and eb.get("左ひじ"):
        check("左腕 tail = 左ひじ head",
              (eb["左腕"].tail - eb["左ひじ"].head).length < 1e-9)
    if eb.get("左手首") and eb.get("左中指１"):
        check("左手首 tail = 左中指１ head",
              (eb["左手首"].tail - eb["左中指１"].head).length < 1e-9)


def case_no_shoulder():
    print("\ncomplete: 无锁骨骨架 → 合成 肩")
    arm_data, _ = build(naming="ue4", has_shoulder=False, spine_segments=3)
    result, arm_obj = run_complete(arm_data)
    eb = arm_obj.data.bones
    check("执行成功", result == {'FINISHED'})
    sh = eb.get("左肩")
    check("左肩 已合成", sh is not None)
    if sh:
        arm = eb.get("左腕")
        check("左肩 在躯干与腕之间", 0 < sh.head.x < arm.head.x,
              f"x={sh.head.x:.3f} vs 腕 x={arm.head.x:.3f}")
        check("左肩 tail = 腕 head", (sh.tail - arm.head).length < 1e-9)


def case_no_toe():
    print("\ncomplete: 无趾骨 → 合成 足先EX 于脚前地面")
    arm_data, _ = build(has_toe=False)
    result, arm_obj = run_complete(arm_data)
    eb = arm_obj.data.bones
    check("执行成功", result == {'FINISHED'})
    toe = eb.get("左足先EX")
    ankle = eb.get("左足首")
    check("左足先EX 已合成", toe is not None)
    if toe and ankle:
        check("足先EX 在地面", abs(toe.head.z) < 1e-6, f"z={toe.head.z:.4f}")
        check("足先EX 在脚踝前方", toe.head.y < ankle.head.y)
        check("足首 tail 指向 足先EX", (ankle.tail - toe.head).length < 1e-9)


def case_no_neck():
    print("\ncomplete: 首 未识别 → 从 頭 合成")
    arm_data, _ = build(drop_roles=("neck_bone",))
    result, arm_obj = run_complete(arm_data)
    eb = arm_obj.data.bones
    check("执行成功", result == {'FINISHED'})
    neck = eb.get("首")
    head = eb.get("頭")
    check("首 已合成", neck is not None)
    if neck and head:
        check("首 在 頭 下方", neck.head.z < head.head.z)
        check("頭 父级为 首/首1",
              head.parent is not None and head.parent.name in ("首", "首1"))


def case_one_arm():
    print("\ncomplete: 右臂缺失 → 按侧降级")
    drop = [k for k in MMD_ARM_RENAMES if k.startswith("right_")
            and ("arm" in k or "hand" in k or "shoulder" in k)]
    arm_data, _ = build(drop_roles=tuple(drop))
    result, arm_obj = run_complete(arm_data)
    eb = arm_obj.data.bones
    check("执行成功(不因右臂缺失中止)", result == {'FINISHED'})
    check("左臂仍完整", eb.get("左肩") is not None and eb.get("左腕") is not None)
    check("右肩 未凭空创建", eb.get("右肩") is None)


def main():
    case_full()
    case_no_shoulder()
    case_no_toe()
    case_no_neck()
    case_one_arm()
    print(f"\n{'ALL PASS' if not _failures else f'{len(_failures)} FAILURES: {_failures}'}")
    sys.exit(0 if not _failures else 1)


if __name__ == "__main__":
    main()
