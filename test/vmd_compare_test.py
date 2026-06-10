# -*- coding: utf-8 -*-
"""
Convert_to_MMD2 端到端验证脚本：XPS → MMD 一键转换，与参考 PMX 并排，套同一 VMD 对比姿态。

在远程 Blender 里运行（通过 BlenderMCP `send_code_to_blender`，或 Blender 文本编辑器 Run Script）：

    import Convert_to_MMD2.test.vmd_compare_test as t   # 若作为插件子模块
    t.run()

或直接把本文件内容整段发给 `mcp__blender__send_code_to_blender`，末尾会自动调用 run()。

设计要点（踩过的坑都固化在这里）：
  * 转换出来的模型是「米」尺度（身高 ~1.7），参考 PMX 是 MMD 原生大单位（身高 ~20）。
  * 缩放对齐用「根 empty 的 scale」，缩放比 = 目标身高 / 转换身高（约 11.9）。
  * 关键：给转换模型导入 VMD 必须用 scale = 1 / 缩放比（约 0.084），
    否则 IK 驱动的腿会崩到 60~100°（FK 的手臂/手指不受影响，因为旋转与尺度无关）。
  * VMD 必须「从干净场景一次性按正确 scale 导入」。先 1.0 再清空重导会污染足IK首帧。
  * 两套骨架的 MMD 名存放位置不同：转换模型在 bone.name（左腕），PMX 在 mmd_bone.name_j。
"""

import bpy
import os
import math
from mathutils import Vector

# ======================================================================
# CONFIG —— 机器相关绝对路径，按需修改（这些是远程 Windows Blender 上的路径）
# ======================================================================
SRC_XPS = r"E:\mywork\mymodel\inase (purifier)_lezisell-A\xps-b.xps"
TGT_PMX = r"E:\mywork\mymodel\Purifier Inase 18\Purifier Inase 18 None.pmx"
VMD     = r"E:\mywork\mymodel\yaoxiang\yaoxiang.vmd"

OUT_DIR        = r"E:\mywork"          # 对比图输出目录
RENDER_FRAMES  = [1, 60, 150]          # 渲染哪些帧的并排图
COMPARE_FRAMES = [1, 10, 75, 150, 220, 295]  # 数值对比采样帧
SIDE_GAP       = 3.0                    # 两模型并排间隙
DO_RENDER      = True                   # 是否渲染对比图

# 期望阈值（用于 PASS/FAIL 判定）
LEG_AVG_TOL    = 10.0   # 腿部各帧平均世界向角差应 < 10°
FK_CONST_TOL   = 0.05   # 上肢角差「跨帧标准差」应 < 此值（恒定=旋转动画一致）

# 关键骨（MMD 标准 name_j）
FK_BONES  = ["上半身2", "上半身3", "首", "左肩", "右肩",
             "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首",
             "左親指１", "左人指１", "左中指１"]
LEG_BONES = ["左足", "左ひざ", "左足首", "右足", "右ひざ", "右足首"]


# ======================================================================
# helpers
# ======================================================================
def _descendants(root):
    out, st = [], list(root.children)
    while st:
        o = st.pop(); out.append(o); st.extend(o.children)
    return out


def _bbox(meshes):
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for m in meshes:
        for c in m.bound_box:
            w = m.matrix_world @ Vector(c)
            for i in range(3):
                mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
    return mn, mx


def _wdir(pb):
    v = pb.tail - pb.head
    return v.normalized() if v.length > 1e-9 else Vector((0, 0, 1))


def _mmd_roots():
    return [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "ROOT"]


# ======================================================================
# steps
# ======================================================================
def clean_scene():
    """删除所有对象 + 无用户的数据块（保留干净场景）。"""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.armatures, bpy.data.meshes, bpy.data.actions):
        for d in list(coll):
            if d.users == 0:
                coll.remove(d)
    print("[clean] 场景已清空")


def check_files():
    miss = [p for p in (SRC_XPS, TGT_PMX, VMD) if not os.path.exists(p)]
    if miss:
        raise FileNotFoundError("缺少文件:\n  " + "\n  ".join(miss))
    print("[files] 三个素材文件都存在")


def import_xps():
    before = {o.name for o in bpy.data.objects}
    bpy.ops.xps_tools.import_model(filepath=SRC_XPS)
    new = [o for o in bpy.data.objects if o.name not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    nmesh = sum(1 for o in new if o.type == "MESH")
    print(f"[1] XPS 导入: 骨架={arm.name} 骨数={len(arm.data.bones)} 网格={nmesh}")
    return arm


def convert(arm):
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    res = bpy.ops.object.one_click_convert()
    # 隐藏备份骨架
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and "backup" in o.name.lower():
            o.hide_set(True); o.hide_render = True
    root = next(o for o in _mmd_roots())
    print(f"[2] 一键转换: {res}  骨数={len(arm.data.bones)}  mmd_root={root.name}")
    return root


def import_pmx():
    before = {o.name for o in _mmd_roots()}
    bpy.ops.mmd_tools.import_model(
        filepath=TGT_PMX, scale=1.0,
        types={"MESH", "ARMATURE", "MORPHS"}, clean_model=True, log_level="ERROR")
    root = next(o for o in _mmd_roots() if o.name not in before)
    print(f"[3] PMX 导入: {root.name}")
    return root


def scale_and_place(conv_root, pmx_root):
    """把转换模型按身高比放大到与目标等高，并排放置，脚底对齐 z=0。返回缩放比。"""
    cm = [o for o in _descendants(conv_root) if o.type == "MESH"]
    pm = [o for o in _descendants(pmx_root) if o.type == "MESH"]
    c0, c1 = _bbox(cm); p0, p1 = _bbox(pm)
    ratio = (p1.z - p0.z) / (c1.z - c0.z)
    conv_root.scale = [s * ratio for s in conv_root.scale]
    bpy.context.view_layer.update()
    c0, c1 = _bbox(cm); p0, p1 = _bbox(pm)
    dx = (((p0.x + p1.x) / 2) + (p1.x - p0.x) / 2 + (c1.x - c0.x) / 2 + SIDE_GAP) \
        - ((c0.x + c1.x) / 2)
    conv_root.location.x += dx
    conv_root.location.z -= c0.z
    pmx_root.location.z -= p0.z
    bpy.context.view_layer.update()
    c0, c1 = _bbox(cm); p0, p1 = _bbox(pm)
    print(f"[4] 缩放比={ratio:.4f}  转换高={c1.z-c0.z:.3f} 目标高={p1.z-p0.z:.3f} "
          f"高度差={abs((c1.z-c0.z)-(p1.z-p0.z)):.4f}")
    return ratio


def import_vmd(conv_root, pmx_root, ratio):
    """干净一次性导入。转换模型用 1/ratio 补偿尺度，目标用 1.0。"""
    def _imp(root, scale):
        bpy.ops.object.select_all(action="DESELECT")
        for o in [root] + _descendants(root):
            try: o.select_set(True)
            except Exception: pass
        bpy.context.view_layer.objects.active = root
        bpy.ops.mmd_tools.import_vmd(filepath=VMD, scale=scale, bone_mapper="PMX")
    _imp(pmx_root, 1.0)
    _imp(conv_root, 1.0 / ratio)
    print(f"[5] VMD 导入: PMX scale=1.0, 转换 scale={1.0/ratio:.5f}")


# ======================================================================
# compare
# ======================================================================
def _bone_maps(conv_root, pmx_root):
    conv_arm = next(o for o in _descendants(conv_root) if o.type == "ARMATURE")
    pmx_arm = next(o for o in _descendants(pmx_root) if o.type == "ARMATURE")
    cmap = {pb.name: pb for pb in conv_arm.pose.bones}                       # 转换: bone.name
    pmap = {pb.mmd_bone.name_j: pb for pb in pmx_arm.pose.bones
            if pb.mmd_bone.name_j}                                           # PMX: name_j
    return conv_arm, pmx_arm, cmap, pmx_arm and pmap


def compare(conv_root, pmx_root):
    conv_arm, pmx_arm, cmap, pmap = _bone_maps(conv_root, pmx_root)

    # ---- FK: 每根骨跨帧角差应恒定（=旋转动画一致，差异仅来自 rest 朝向）----
    print("\n== 上肢/躯干 世界向角差（恒定=旋转动画一致）==")
    print(f"{'bone':<8}" + "".join(f"f{f:<6}" for f in COMPARE_FRAMES) + "  跨帧σ")
    fk_ok = True
    for k in FK_BONES:
        cb, pb = cmap.get(k), pmap.get(k)
        if not cb or not pb:
            continue
        vals = []
        for f in COMPARE_FRAMES:
            bpy.context.scene.frame_set(f)
            vals.append(math.degrees(_wdir(cb).angle(_wdir(pb))))
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        if std > FK_CONST_TOL:
            fk_ok = False
        print(f"{k:<8}" + "".join(f"{v:<7.2f}" for v in vals) + f"  {std:.3f}")

    # ---- 腿部 IK: 各帧平均应小 ----
    print("\n== 腿部 世界向角差（IK，scale 修正后应小）==")
    print(f"{'bone':<8}" + "".join(f"f{f:<6}" for f in COMPARE_FRAMES))
    agg = {f: [] for f in COMPARE_FRAMES}
    for k in LEG_BONES:
        cb, pb = cmap.get(k), pmap.get(k)
        if not cb or not pb:
            continue
        row = f"{k:<8}"
        for f in COMPARE_FRAMES:
            bpy.context.scene.frame_set(f)
            a = math.degrees(_wdir(cb).angle(_wdir(pb)))
            row += f"{a:<7.2f}"; agg[f].append(a)
        print(row)
    leg_avgs = {f: (sum(v) / len(v) if v else 0) for f, v in agg.items()}
    leg_max_avg = max(leg_avgs.values()) if leg_avgs else 0
    print("腿部各帧 avg:", {f: round(a, 1) for f, a in leg_avgs.items()})

    leg_ok = leg_max_avg < LEG_AVG_TOL
    print("\n========== 判定 ==========")
    print(f"  FK 旋转一致(跨帧σ<{FK_CONST_TOL}): {'PASS' if fk_ok else 'FAIL'}")
    print(f"  腿部 IK 各帧 avg<{LEG_AVG_TOL}°  : {'PASS' if leg_ok else 'FAIL'} "
          f"(最差帧 avg={leg_max_avg:.1f}°)")
    print(f"  >>> 总体: {'PASS ✅' if (fk_ok and leg_ok) else 'FAIL ❌'}")
    return fk_ok and leg_ok


def render_compare(conv_root, pmx_root):
    if not DO_RENDER:
        return
    scene = bpy.context.scene
    cm = [o for o in _descendants(conv_root) if o.type == "MESH"]
    pm = [o for o in _descendants(pmx_root) if o.type == "MESH"]
    c0, c1 = _bbox(cm); p0, p1 = _bbox(pm)
    cx = (min(c0.x, p0.x) + max(c1.x, p1.x)) / 2
    cz = (max(c1.z, p1.z)) / 2
    width = max(c1.x, p1.x) - min(c0.x, p0.x)

    cam = bpy.data.objects.get("cmp_cam_obj")
    if not cam:
        cd = bpy.data.cameras.new("cmp_cam"); cd.type = "ORTHO"
        cam = bpy.data.objects.new("cmp_cam_obj", cd)
        scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = width * 1.1
    cam.location = (cx, -90, cz)
    cam.rotation_euler = (math.radians(90), 0, 0)
    scene.camera = cam

    if "cmp_sun" not in bpy.data.objects:
        ld = bpy.data.lights.new("cmp_sun_d", "SUN"); ld.energy = 3
        s = bpy.data.objects.new("cmp_sun", ld); scene.collection.objects.link(s)
        s.rotation_euler = (math.radians(60), 0, math.radians(30))

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    for f in RENDER_FRAMES:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(OUT_DIR, f"compare_f{f}.png")
        bpy.ops.render.render(write_still=True)
    print(f"[render] 已输出 {len(RENDER_FRAMES)} 张对比图到 {OUT_DIR} "
          f"(compare_f*.png, 左=目标PMX 右=转换模型)")


# ======================================================================
# entry
# ======================================================================
def run():
    print("=" * 60)
    print("Convert_to_MMD2  XPS→MMD + VMD 对比测试")
    print("=" * 60)
    check_files()
    clean_scene()
    arm = import_xps()
    conv_root = convert(arm)
    pmx_root = import_pmx()
    ratio = scale_and_place(conv_root, pmx_root)
    import_vmd(conv_root, pmx_root, ratio)
    ok = compare(conv_root, pmx_root)
    render_compare(conv_root, pmx_root)
    print("\n测试结束。")
    return ok


if __name__ == "__main__":
    run()
