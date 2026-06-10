# Convert_to_MMD2 — 远程连接 & 测试指南

本指南让一个**全新的 Claude 会话**（从本目录打开）或人，能够：
连接远程 Blender → 部署本插件 → 跑一遍 XPS→MMD 一键转换 → 与参考 PMX 并排对比验证。

> ⚠️ **机器相关的具体值**（远程主机 IP、面板密码、cli.py 路径、测试素材路径、插件目录）
> 都在 **`docs/remote.local.md`** —— 那是**本地文件，已被 `.gitignore`，不会提交到仓库**
> （含密码 + 一个无鉴权的远程代码执行端口，绝不能进公开仓库）。
> **先读 `docs/remote.local.md`**，用里面的真实值替换本文中的占位符：
> `<VPS_HOST>` `<PANEL_PW>` `<CLI_PY>` `<ADDON_DIR>` `<REMOTE_TMP>` `<SRC_XPS>` `<TGT_PMX>` `<VMD>`。

---

## 0. 架构 & 前置

远程是一台 **Windows 上的 Blender 3.6.15**，已安装并启用：`mmd_tools`、`XNALaraMesh`（XPS 导入器）。
两条隧道（细节见 `remote.local.md`）：

| 端口 | 用途 | 怎么用 |
|------|------|--------|
| **9876** | BlenderMCP —— 在 Blender 里执行 Python | Claude 用 `mcp__blender__*` 工具；或 TCP 回退到 `<VPS_HOST>:9876` 发 `{"type":"execute_code","params":{"code":...}}` |
| **9090** | Web 面板 —— 上传/下载文件 | 本机 `python3 <CLI_PY> --server http://<VPS_HOST>:9090 --password <PANEL_PW> upload/download ...` |

**第一步永远先测连通**（Claude）：调用 `mcp__blender__test_connection`，期望 `Connection OK!`。
若 9876 拒绝连接 → 9876 隧道挂了，按 `remote.local.md` 的命令重启隧道。

---

## 1. 部署本插件到远程 Blender

在**本目录的上一级**打包（用 `COPYFILE_DISABLE=1` 避免 macOS 生成 `._*` 资源叉文件），上传到远程临时目录：

```bash
# 本机（Mac），cwd = Convert_to_MMD2
cd ..
COPYFILE_DISABLE=1 tar czf /tmp/cmmd2.tgz --exclude='__pycache__' --exclude='.git' Convert_to_MMD2
python3 <CLI_PY> --server http://<VPS_HOST>:9090 --password <PANEL_PW> \
    upload /tmp/cmmd2.tgz "<REMOTE_TMP>/cmmd2.tgz"
# 注意：面板会把 basename 追加到目录后 → 实际落点是 "<REMOTE_TMP>/cmmd2.tgz/cmmd2.tgz"
```

然后在 Blender 里（`mcp__blender__send_code_to_blender`）解压 + 启用：

```python
import tarfile, os, shutil, sys, bpy
src = r"<REMOTE_TMP>/cmmd2.tgz/cmmd2.tgz"           # 见上面的 basename 追加
addons = r"<ADDON_DIR>"                              # ...Blender/3.6/scripts/addons
dst = os.path.join(addons, "Convert_to_MMD2")
if os.path.exists(dst): shutil.rmtree(dst)
with tarfile.open(src) as t: t.extractall(addons)
# 清掉 macOS AppleDouble 残留（若用了 COPYFILE_DISABLE 一般为 0）
for root,_,files in os.walk(dst):
    for f in files:
        if f.startswith("._"): os.remove(os.path.join(root,f))
# 纯净重载
for m in [m for m in sys.modules if m=="Convert_to_MMD2" or m.startswith("Convert_to_MMD2.")]:
    del sys.modules[m]
bpy.ops.preferences.addon_enable(module="Convert_to_MMD2")
print("enabled; one_click op:", hasattr(bpy.types,"OBJECT_OT_one_click_convert"))
```

### ⚠️ 坑：与原版 Convert_to_MMD 的 bl_idname 撞车
原版插件与本插件**共用相同的 `bl_idname`**。两者同时启用时，后注册的覆盖先注册的；
且禁用其中一个会因 RNA 冲突在 `unregister` 抛错。**确保本插件最后注册**，并中和旧插件：

```python
import sys, bpy
old = sys.modules.get("Convert_to_MMD")
if old:                                   # 让旧插件的 register/unregister 变空操作
    old.register = lambda: None; old.unregister = lambda: None
# 重新注册本插件，保证它的 operator 生效
bpy.ops.preferences.addon_disable(module="Convert_to_MMD2")
for m in [m for m in sys.modules if m=="Convert_to_MMD2" or m.startswith("Convert_to_MMD2.")]:
    del sys.modules[m]
bpy.ops.preferences.addon_enable(module="Convert_to_MMD2")
# 确认 operator 绑到本包：
print(bpy.types.OBJECT_OT_one_click_convert.__module__)   # 期望 Convert_to_MMD2.convert.pipeline
```

> 重新部署改动后的代码：重复「上传 → 解压 → 纯净重载」即可（每次 `del sys.modules` 后 `addon_enable`）。

---

## 2. 跑一键转换（⚠️ 必须用轻量 override）

```python
import bpy
# 清场到只剩相机/灯
for o in list(bpy.data.objects):
    if o.type not in ('CAMERA','LIGHT'): bpy.data.objects.remove(o, do_unlink=True)

win = bpy.context.window_manager.windows[0]; scr = win.screen
area = next(a for a in scr.areas if a.type=='VIEW_3D')
region = next(r for r in area.regions if r.type=='WINDOW')

# 导入 XPS
with bpy.context.temp_override(window=win, area=area, region=region, screen=scr):
    bpy.ops.object.import_xps(filepath=r"<SRC_XPS>", auto_scale=True)
arm = next(o for o in bpy.data.objects if o.type=='ARMATURE')

# 一键转换：先 select + 设 active，再用「轻量」override（只给 window/area/region/screen）
bpy.ops.object.select_all(action='DESELECT'); arm.select_set(True)
bpy.context.view_layer.objects.active = arm
with bpy.context.temp_override(window=win, area=area, region=region, screen=scr):
    bpy.ops.object.one_click_convert(auto_identify=True)
```

### ⚠️⚠️ 关键坑：轻量 override，不要 pin active_object
`one_click_convert` 内部的 `fix_forearm/align_arms/align_fingers` 会 `view_layer.objects.active = <mesh>`
再 `modifier_apply` 把姿态烘焙进**网格**。如果外层 `temp_override` **钉死了 `active_object=骨架`**，
`modifier_apply` 会作用到骨架（空操作）→ **骨头转了、网格没烘焙** → 手指（尤其拇指，转 ~31°）和手臂
与网格错位、留下 `_copy` 修改器。**所以：override 里只放 `window/area/region/screen`；用之前先
`select_set` + `view_layer.objects.active`；绝不要在 override 里写 `active_object`/`object`/`selected_objects`。**
（在真实 UI 里点按钮不会钉 active_object，所以插件本身是对的；这纯粹是 MCP 调用的坑。）

**期望日志**：`一键转换完成: 20/20 步成功`（2026-06 重构后新增 7.8 权重收尾；旧基线为 19/19），转换后骨架 196 骨，`手部权重修正: 拇指渗出 177 顶点→手首, 掌部 1059 顶点→掌骨`。

---

## 3. 并排对比 + 渲染 f250

```python
import bpy
win = bpy.context.window_manager.windows[0]; scr = win.screen
area = next(a for a in scr.areas if a.type=='VIEW_3D'); region = next(r for r in area.regions if r.type=='WINDOW')
conv = next(o for o in bpy.data.objects if o.type=='ARMATURE' and 'backup' not in o.name.lower())

# 导入参考 PMX（scale=0.083956 使其与转换结果同高，约 1.75m）
before = {o.name for o in bpy.data.objects}
with bpy.context.temp_override(window=win, area=area, region=region, screen=scr):
    bpy.ops.mmd_tools.import_model(filepath=r"<TGT_PMX>", scale=0.083956)
tgt = next(o for o in bpy.data.objects if o.type=='ARMATURE' and o.name not in before)

# 两个模型都加载 yaoxiang.vmd
def load_vmd(a):
    bpy.ops.object.select_all(action='DESELECT'); a.select_set(True); bpy.context.view_layer.objects.active=a
    with bpy.context.temp_override(window=win, area=area, region=region, screen=scr):
        bpy.ops.mmd_tools.import_vmd(filepath=r"<VMD>", scale=0.083956, bone_mapper='PMX')
load_vmd(conv); load_vmd(tgt)   # conv→634 fcurves, tgt→676

# 偏移根 ±0.7（不要再缩放：两者已同高）
def root(a):
    while a.parent: a=a.parent
    return a
root(conv).location.x=-0.7; root(tgt).location.x=0.7   # conv 根=New MMD Model, tgt 根=Purifier...

# 相机 + 引擎 + 帧；务必把输出设成 PNG（默认可能是视频格式 → 报错）
sc=bpy.context.scene
sc.frame_start=1; sc.frame_end=295; sc.frame_set(250)
sc.render.engine='BLENDER_WORKBENCH'; sc.render.image_settings.file_format='PNG'
sc.render.resolution_x=sc.render.resolution_y=1280
cam=bpy.data.objects.get('CMP_CAM') or bpy.data.objects.new('CMP_CAM', bpy.data.cameras.new('CMP_CAM'))
if cam.name not in bpy.context.scene.collection.objects: sc.collection.objects.link(cam)
cam.data.type='ORTHO'; cam.data.ortho_scale=3.2
cam.location=(0.0,-6.0,0.85); cam.rotation_euler=(1.5708,0,0); sc.camera=cam
sc.render.filepath=r"<REMOTE_TMP>/mmd2_cmp_f250.png"
bpy.ops.render.render(write_still=True)
```

下载渲染图到本机查看：

```bash
python3 <CLI_PY> --server http://<VPS_HOST>:9090 --password <PANEL_PW> \
    download "<REMOTE_TMP>/mmd2_cmp_f250.png" /tmp/mmd2_cmp_f250.png
# 然后用 Read 工具看 /tmp/mmd2_cmp_f250.png
```

> 若 `cli.py` 报 `127.0.0.1:9090 connection refused` —— 本地 9090 隧道没起，但用 `--server http://<VPS_HOST>:9090` **直连 VPS** 即可（见上，本就是直连）。

---

## 4. 验证清单（期望值 = 上游手调基线）

在 Blender 里跑下面的检查，对照期望值：

```python
import bpy, math
arm = next(o for o in bpy.data.objects if o.type=='ARMATURE' and o.name=='Armature')
b = arm.data.bones
print("bones:", len(b))                                   # 期望 196
print("_dummy_:", sum(n.name.startswith('_dummy_') for n in b),   # 期望 20
      "_shadow_:", sum(n.name.startswith('_shadow_') for n in b)) # 期望 20
# 肩C 应是「直接约束」(无中转)：
pb = arm.pose.bones['左肩C']
print("左肩C cons:", [(c.type,c.subtarget) for c in pb.constraints])  # 期望 [('TRANSFORM','左肩P')]
# 每个网格只 1 个 armature 修改器（去重，防炸网格）：
print("dup arm-mods:", [m.name for m in bpy.data.objects if m.type=='MESH'
      and len([d for d in m.modifiers if d.type=='ARMATURE' and d.object==arm])>1])  # 期望 []
```

**运动等价**（vs 参考 PMX，f250；目标骨名用 `.L/.R`）：上臂 **0.0°**、前臂 ~7.7°、手 ~5°、腿 1–2°、脊柱 0.0°。
（脚本见本仓库提交历史里这次验证用的代码，或 `docs/remote.local.md` 附的片段。）

**权重抽查**（body mesh，左侧）：掌骨 `左人指０≈74` / `左中指０≈55`，拇指/掌部移动顶点 `177 / 1059` —— 与上游一致即未回退。

---

## 5. 已知坑速查

| 坑 | 对策 |
|----|------|
| **MCP 转换错位**（手指/手臂） | 轻量 override，转换前 select+active，**不要** pin `active_object`（见 §2） |
| **bl_idname 撞车** | 中和旧 `Convert_to_MMD`，本插件最后注册（见 §1） |
| **`Cannot write a single file`** | `render.image_settings.file_format='PNG'`（默认可能是视频格式） |
| **macOS `._*` 资源叉** | 打包用 `COPYFILE_DISABLE=1 tar`；或解压后删 `._*` |
| **`cli.py` 拒连 127.0.0.1:9090** | 本地隧道没起，`--server http://<VPS_HOST>:9090` 直连 VPS |
| **9876 拒连** | 9876 隧道挂了，按 `remote.local.md` 重启 |
| **导入/转换 "Context missing active object"** | 用 `temp_override(window/area/region/screen)`，win0 的 "Layout" 屏有 VIEW_3D |
| **目标 PMX 不缩放** | `import_model` 的 `scale` 在此环境无视觉效果；用 `scale=0.083956` 即同高，靠根 `location.x` 摆并排 |

---

## 附：素材与目标

- 源 XPS / 参考 PMX / 动作 VMD 的路径、参考 PMX 缩放(0.083956)、远程插件目录、临时目录、cli.py 路径、
  VPS 主机/端口/密码、隧道重启命令 —— 全部在 **`docs/remote.local.md`**（本地、未提交）。
- 本插件与原版 `Convert_to_MMD` 共享 `bl_idname`，**测试时只启用其一**。
