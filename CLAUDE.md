# CLAUDE.md

Convert to MMD 2 — XPS/XNALara 骨架一键转 MMD 的 Blender 插件(骨骼管理引擎重构版)。

## 测试约定

- **测试的高度都以目标对齐**:验证转换结果时,把转换出来的模型**缩放到与目标 PMX 等高**(用根 empty 的 scale,缩放比 = 目标身高 / 转换身高,本测试集约 11.91×),再并排对比。不要用米尺度的小模型比,位移/偏差数值会太小看不清。
- 直接后果——**VMD 导入尺度**:转换模型是「米」尺度,给它导入 VMD 必须用 `scale = 1 / 缩放比`(≈0.084);目标 PMX 用 `scale = 1.0`。否则 IK 腿会崩到 60~100°(FK 旋转与尺度无关,不受影响)。
- VMD 从干净场景**一次性按正确 scale 导入**,不要先 1.0 再清空重导(会污染足IK首帧)。
- 骨名映射:转换模型 MMD 名在 `bone.name`(如 `左腕`);目标 PMX 在 `mmd_bone.name_j`。对比时分别取。
- 端到端测试脚本:`test/vmd_compare_test.py`(顶部 CONFIG 放素材绝对路径),详见 `test/README.md`。

## 远端 Blender

- 通过 BlenderMCP(`mcp__blender__*`)在远端 Windows Blender 3.6.15 执行 Python。
- 机器相关值(主机/密码/路径/素材)在 `docs/remote.local.md`(已 gitignore);连接与部署流程见 `docs/TESTING.md`。

## 权重处理原则

- 重分配一律**位置驱动 + 守恒**(twist 按轴向 t、palm 按手掌深度 d、debleed 按拇指轴 u + 前腕位置斜坡),**不要 per-target 魔数**。
- 手部权重链:`twist`(步7,切 腕/ひじ 捩骨 + 回收手首前腕段)→ `palm`(步7.5,debleed 親指０ + 掌部分掌骨)。手部权重的最后一次**语义**编辑在 7.5,改手部分法就改这里;步7.8 `sanitize` 只做剔渣/4骨/归一,不改分布语义。
- **helper 权重折叠**(步1.4/2.5,`weights/fold.py`+`transfer.py`):名字无关。段上 helper(UE/Daz/Valve/foretwist 各种 twist 拓扑)按权重质心**整组折进段池**(腕/ひじ/手首),让步7的 τ 切分统一重分级;别在 fold 里直接分捩骨。物理链(裙/发/尾/胸,classifier 'preserve')绝不消费。
- **不要信骨 tail/roll**:XPS 骨只有 head,tail 是 XNALaraMesh 合成的;几何判定一律用 head 链 + 顶点云(complete 之后我们自己设的 MMD 主骨 tail 可用)。
- 识别/分类的几何阈值一律取**骨架高度 H 的比例**,禁止绝对米常量。

## 离线测试(无需 Blender)

```bash
python3 test/offline/run_identify_tests.py   # 14 合成骨架族识别 + 分类器
python3 test/offline/run_weight_tests.py     # 真实 transfer→twist→palm→sanitize 数值断言
python3 test/offline/run_complete_tests.py   # 缺骨合成/按侧降级
```
改识别/分类/权重/补全代码必须先过这三套(fake_bpy 驱动**真实插件代码**;设计与调研见 `docs/any-xps.md`)。远端可用时再跑 `test/vmd_compare_test.py` 做标定模型回归。
