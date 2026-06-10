# Convert to MMD 2

将外部骨骼格式（XPS / XNALara 等）**一键转换为 MMD（MikuMikuDance）格式**的 Blender 插件 —— 在原版 [Convert to MMD](https://gitee.com/UITCIS/Convert-to-MMD)（作者 **UITCIS / 空想幻灵**）基础上，对**骨骼管理引擎**做了一次从零重构。

本仓库**只包含重构后的骨骼管理部分**（精简、可独立安装），不含原版的物理/导入/开发者工具。原版仍是功能更全的上游。

---

## 这次重构做了什么

| 目标 | 落地 |
|------|------|
| **先复用 XPS 权重，切分单独梳理** | `convert/weights/` 子包把「复用」(`transfer`) 与「切分/合成」例外(`chain` / `twist` / `palm`)彻底分开；目标 PMX 的标定常量逐字保留 |
| **优先复用 mmd_tools 能力** | 格式转换用 `convert_to_mmd_model`；所有付与(additional transform)中转链交给 `apply_additional_transform` |
| **统一 dummy / shadow / transform 骨** | 删除腿D/肩P 约 300 行手写 `_dummy_`/`_shadow_`+约束；改为**只设 `mmd_bone` 付与 → 单次 `apply_additional_transform`**，由 mmd_tools 自动选择：**对齐→直接约束，错位→dummy/shadow 中转** |
| **逻辑更正确** | 单一付与表、共享 mesh/权重 helper（消除约 8 处重复）、去掉冗余的多处 grant 设置 |
| **操作角度不变** | 所有 `bl_idname` 与面板布局与原版一致 |

> **次标准骨的中转链选择（核心设计）**：只有「捩骨子骨」需要 `_dummy_`/`_shadow_` 中转——它们显示朝上、却跟随沿臂的主捩骨（不同坐标系）。腿D/肩C 与各自付与源对齐，mmd_tools 会直接建本地约束，无需中转。验证发现 **肩C 拿到的就是直接约束**，比原版手写少建了一套多余的中转骨。

---

## 转换流程（一键）

```
自动识别 → 归正 → 重命名 → 转移/折叠helper权重 → 前臂/上臂/手指对齐 → 补全缺失骨
→ MMD IK → 骨骼集合 → mmd_tools 转换
→ 腿D → 捩骨 → 手部权重修正 → 权重收尾(剔渣+4骨+归一) → 肩P
→ 设付与 → apply_additional_transform（统一建全部中转链）
```

## 任意 XPS 泛化（2026-06 重构）

识别与权重处理对**任意来源的 XPS 模型**泛化（调研、失败矩阵与设计见 [`docs/any-xps.md`](docs/any-xps.md)）：

- **识别尺度无关**：所有几何阈值按骨架高度取比例；fork 需肢链证据（手部签名/落地深度），裙·发·翼链偷不走；臂链按关节评分分段，Daz 链内 twist 骨（lShldrTwist 系）不再误当肘/手。
- **权重折叠引擎**（`weights/fold.py`）：名字无关地消费三种 twist 拓扑（UE 侧挂 `*_twist_*`、Daz 链内 Bend/Twist、Source Ulna/Wrist、XPS foretwist）——按权重质心折进 腕/ひじ/手首 段池，再由 τ 切分按位置重新分级，与原生 XPS 权重同路径；肩帽 helper 仍走 deltoid 斜坡。
- **物理链保留**：裙/发/尾/胸/饰带按结构判定（深链 + 子树无标准骨 + 不沿臂轴）整链 preserve，供后续加刚体/joint。
- **权重收尾**（`weights/sanitize.py`，步 7.8）：剔 <0.5% 残渣、每顶点 ≤4 骨、归一化——XPS 输入可非归一/超 4 骨，mmd_tools 导出只做盲 top4 截断，截断决策收归转换器。
- **缺骨降级**：缺 肩/首/趾 自动合成、单侧缺臂/腿按侧跳过，管线不再 KeyError 中止。
- **离线回归门**：`test/offline/` 用合成骨架族（14 命名/结构变体 × 权重场景）驱动真实插件代码，无需 Blender。

## 目录结构

```
Convert_to_MMD2/
├─ __init__.py / ui.py / presets.py        注册 / 精简面板 / 槽位填充
├─ bone_map_and_group.py · bone_utils.py
│  skeleton_identifier.py · helper_classifier.py
│  properties.py · encoding_patch.py        与骨名无关的基础模块（原样复用）
├─ presets/                                 28 个骨架预设 + 2 个 canonical 方向
└─ convert/                                 转换引擎
   ├─ pipeline.py                           一键流程编排
   ├─ identify / correct / rename / complete / align / ik / groups / mmd_convert
   ├─ semistandard.py                       捩骨 + 腿D + 肩P（纯几何构建）
   ├─ grants.py                             唯一的付与(additional_transform)表
   └─ weights/                              req1：复用 vs 切分 分离
      ├─ common.py                          共享 mesh/vgroup/轴 helper
      ├─ fold.py                            折叠决策：helper 权重 → 段池（纯几何，可离线测）
      ├─ transfer.py                        复用路径：deltoid 斜坡 / 段折叠 / 就近
      ├─ chain.py                           切分：上半身1 / 首1 + 腋窝平滑
      ├─ twist.py                           切分：τ 曲线捩骨权重（守恒）
      ├─ palm.py                            合成：手掌→掌骨 + 拇指去渗出
      └─ sanitize.py                        收尾：剔渣 + 每顶点4骨 + 归一化
```

## 依赖

- Blender **3.0+**（在 3.6.15 上验证）
- [**mmd_tools**](https://extensions.blender.org/add-ons/mmd-tools/)（必需：格式转换 + 付与中转链）
- 导入 XPS 源模型需 **XNALaraMesh**（本插件不含导入，依赖独立安装）

## 安装

1. 把 `Convert_to_MMD2` 目录放进 Blender 的 `scripts/addons/`（或打包成 zip 后从偏好设置安装）。
2. 偏好设置 → 插件，启用 **Convert to MMD 2**。
3. 视图右侧栏出现 **Convert to MMD** 面板。

> 原版 Convert to MMD 与本插件共用相同的 `bl_idname`，**不要同时启用两者**（否则操作符会互相覆盖）。

## 使用

1. 用 XNALaraMesh 导入 XPS 模型，选中骨架。
2. 面板「主骨骼管理」→ **一键转换 XPS→MMD**（自动识别骨架并跑完整流程）。
   - 也可点 **自动识别骨架** 填充槽位后，手动逐步执行 1~5。
3. 用 mmd_tools 导出 PMX。

## 验证

在远端 Blender 3.6.15 上对一个真实 XPS 模型做了端到端验证：一键转换 19/19 步通过，196 骨骼，权重与上游手调结果逐字一致（掌骨 人74/中55、拇指/掌部 177/1059），加载 VMD 动作后与参考 PMX 并排播放姿态一致、无炸网格；运动等价（vs 目标 PMX）上臂 0.0°、前臂 ~8°、腿 1~2°。

## 致谢与许可

- 原版 **Convert to MMD** 作者：**UITCIS（空想幻灵）** — [Gitee](https://gitee.com/UITCIS/Convert-to-MMD) · [B站](https://space.bilibili.com/43768997)
- 本仓库为其骨骼管理部分的重构衍生版，遵循同一许可证 **GPL-3.0**（见 [`LICENSE`](LICENSE)）。
