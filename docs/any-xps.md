# 任意 XPS → MMD 泛化重构 — 调研、设计与实施记录（2026-06-10）

> 目标：让转换器对**任意来源的 XPS 模型**都能产出正确的 MMD 模型，权重正确性是核心。
> 本文 = ① 调研结论（带来源）② 重构前的失败矩阵 ③ 架构改动 ④ 离线验证体系 ⑤ 遗留事项。

---

## 1. 调研结论（权重相关，全部带来源核实）

### 1.1 XPS 格式与导入器的地面真值

| 事实 | 对转换器的约束 |
|---|---|
| XPS 骨骼只有 **名字 + 父索引 + head 位置** 三个字段，无 tail/roll/约束/procedural 机制（[GLLara 格式文档](https://github.com/cochrane/GLLara/blob/main/Documentation/XNALara%20Model%20File%20Format.md)） | **tail 和 roll 是 XNALaraMesh 合成的**（tail=子骨 head 平均，无子时沿父骨方向延伸）——任何几何判定只能依赖 head 链与顶点云，**绝不能信 tail** |
| 权重旧格式固定 4 组；XPS 11.8.9 的 v3 格式**每顶点可变数量**；格式**不要求归一化**，XNALaraMesh 原样写入不重归一 | 转换器必须自己做 归一化 + 4 骨限制（见 §3.5 sanitize） |
| 「unused」前缀是 **XPS 程序官方惯例**（隐藏骨、排除 mirror pose），但**保留原始游戏骨名的 helper 一样常见**（ValveBiped、bip001 xtra、UE twist 等移植大量原名保留） | 「unused」只能当强提示，**不能当完备过滤器** —— 这正是重构前权重处理的最大窟窿 |
| mmd_tools 导出 PMX 时对 >4 骨顶点：**按权重排序取 top4 + 重归一化，无小权重剔除阈值**（[exporter.py 源码](https://github.com/MMD-Blender/blender_mmd_tools/blob/main/mmd_tools/core/pmx/exporter.py)） | 截断决策要握在转换器手里：导出前自做 剔渣(<0.5%)+limit4+归一 |

### 1.2 XPS 生态的 twist 辅助骨三种拓扑（权重泛化的核心敌人）

XPS 没有约束系统 → 游戏移植里的 twist/procedural 骨全部变成**带权重的死骨**：
VMD 不驱动它们、它们僵硬跟随父骨 → 绑在它们上面的顶点**糖纸扭曲原样保留**，
而 twist.py 的 τ 切分只切 腕/ひじ 顶点组、看不见这些权重。

| 拓扑 | 代表 | 形态 |
|---|---|---|
| **链内串联** | Daz G3/G8 `lShldrBend→lShldrTwist→lForearmBend→lForearmTwist`；3ds Max Biped Twist Links | twist 骨是主链一环（是下一段的父骨） |
| **侧挂子骨** | UE `upperarm_twist_01_l`/`lowerarm_twist_01_l`；Source `ValveBiped Ulna/Wrist`；XPS `foretwist 1/2` | 挂在段骨下的叶子/短链 |
| **无 twist** | XNALara 默认（TombRaider 系） | twist 已烘焙进 elbow/wrist 混合权重（远端前臂绑手骨是结构性习惯） |

### 1.3 MMD 侧的权重期望（社区/插件标准做法）

- **腕捩/手捩**：权重沿臂轴梯度切分（そぼろ準標準插件加骨时自动重分配，与本仓库 twist.py 同构）；**捩骨轴限制必须指定且先端正确**（腕捩→ひじ、手捩→手首），否则手臂塌陷——`semistandard._fix_twist_axis` 已覆盖。
- **足D 系**：足/ひざ/足首 **零权重**，权重整组改名到 D 骨，脚尖给 足先EX —— `semistandard` 的 VG 改名已是正确做法。
- **肩P/肩C 零权重**，仅付与（肩C←肩P×-1）—— 已正确。
- **未映射 helper**：PMXEditor 标准操作是「ウェイト転送/置換」把权重并回主骨后删骨，**绝不无转移删组**。
- **物理链**（裙/发/尾/胸）：**保留 FK 骨链与权重**（它们就是后续刚体+joint 的骨架）；胸的社区移植惯例 = 每侧恰好 1 根胸骨。

---

## 2. 重构前失败矩阵（离线合成骨架实测）

`test/offline/run_identify_tests.py` 用 14 个合成骨架族驱动真实识别代码，重构前 **1/14 通过**：

| 失败 | 根因 |
|---|---|
| 手指中/薬/小指全错位（所有命名族） | 按「到拇指根 3D 距离」排序不可靠（各指根伸出长度不同） |
| 0.17m 模型识别全灭 | 0.01/0.02 等**绝对米阈值**不随尺度缩放（识别还跑在 auto-scale 之前） |
| Daz 链内 twist：肘=lShldrTwist、手=lForearmBend、手指全空 | 臂链按**位置槽** arm[0..3] 分配，没有关节判定 |
| 裙链根骨 cls=pelvis → 权重并进下半身 | pelvis 判据没有排除「带长链的子骨」，毁掉物理候选链 |
| （权重）UE/Valve/Daz 带名 twist 骨权重无人消费 | transfer 只认 `unused*` 前缀 |
| （健壮性）缺 首/肩/腕 任一 → complete KeyError → 整管线中止 | bp 表硬索引 |

---

## 3. 架构改动

### 3.1 `skeleton_identifier.py` — 尺度无关 + 验证式识别
- 所有几何阈值改为**骨架高度 H 的比例**（0.006H≈旧 0.01@1.7m，米尺度行为不变）。
- **fork 验证**：腿 fork 要求两侧链「落差>0.22H + 弧长>0.25H +（加分）足部转折」；臂 fork 要求两侧有**手部签名**（3+ 指链）。裙/翼/大衣链不再能偷走 fork。
- **臂链关节评分分段**（替代位置槽）：在 起点→手 的原始链上枚举 (上臂,肘) 组合，按「上臂/前臂长度比≈1.1 + 名字提示(twist 减分/elbow 加分) + 弯角加分」选关节——链内 twist 骨被自然跳过，T-pose 也成立。
- **手指**：拇指=「最偏方向 + 根最贴腕」联合评分；其余指沿**掌横向轴**（远离拇指方向）排序，不再按距离。
- 名字仅作低权重 tie-breaker（garbage 命名照样识别）。

### 3.2 `helper_classifier.py` — 物理链结构判定
- 阈值尺度相对化。
- **物理链判定**：深度≥3 的链、且**子树不含任何 mapped 骨**、且**不沿臂段走向** → 整链 preserve（裙/发/尾/饰带），preserve 沿链向下传播。
  - 「子树含 mapped」排除 Daz 链内 twist（它的子树包着整条手臂）→ 落到段判定 → twist（可折叠）。
  - 「沿臂段走向」区分 foretwist 链（沿臂，可折叠）与前臂饰带（垂下，preserve）。

### 3.3 `convert/weights/fold.py`（新）+ `transfer.py` — 通用 helper 折叠引擎
权重决策阶梯（每个被消费的 helper，先命中先用）：
1. **deltoid**：肩帽 helper（质心 t∈[0.05,0.55]、横向<0.5臂长）→ 按斜坡分 肩/腕（标定常量逐字保留）。
2. **段折叠**：权重质心落在 上臂/前臂/掌 段管内（横向<0.5段长）→ **整组折进段池骨**（腕/ひじ/手首）。
   名字无关——UE/Valve/Daz/foretwist 全覆盖。折叠发生在 τ 切分（步7）之前，τ 曲线按顶点位置把折回的权重重新分级到 腕捩/手捩 系，**与原生 XPS 臂权重走完全相同的路径**。
3. **逐顶点最近**：脊柱 merge/其余 unused → 最近有效变形骨（旧行为保留）。
   pelvis 类 → 下半身；preserve/脸/手细节骨 → 不动。

消费集合的变化：旧版只消费 `unused*` 前缀；新版凡 classifier 标 `twist` 的段上 helper 都消费（fold 只动顶点组、不动骨层级，链内 twist 骨本体保留不破坏父子链）。

### 3.4 `convert/complete.py` — 缺骨合成与按侧降级（绝不 KeyError）
- 缺 首↔頭 互相合成；缺 肩 → 从胸/腕几何合成（无权重锁骨）；缺趾 → 足先EX 合成在**脚踝正前方地面**（不再信导入器的 足首 tail）。
- 手臂/腿**按侧独立**：缺一侧只跳过该侧并打印降级说明，不再中止管线。`ik.py` 同样按侧降级。

### 3.5 `convert/weights/sanitize.py`（新）— 权重收尾（管线步 7.8）
逐顶点：剔除 <0.005 残渣 → 保留最大 4 骨 → 归一化。动机见 §1.1（XPS 输入可非归一/可>4 骨；fold+τ+palm 链路可产生 5+ 组顶点；mmd_tools 导出只做盲 top4）。只动变形骨组，不碰 mmd 元数据组。

### 3.6 不动的部分（刻意）
- twist τ 曲线、reclaim、palm/debleed 的全部标定常量逐字保留（README 的回归承诺）。
- 大腿/臀部 helper 维持 preserve（变形等价于折叠，且保留物理/二改余地）。
- 管线步序与 bl_idname 全部不变（新增 7.8 一步）。

## 4. 离线验证体系（远端 Blender 不可用时的回归门）

`test/offline/`（纯 Python，无需 Blender；`mathutils` 用纯 Python 替身，`fake_bpy` 提供最小 bpy 表面驱动**真实插件代码**）：

```bash
python3 test/offline/run_identify_tests.py   # 14 骨架族 × 30 角色 + 分类器断言
python3 test/offline/run_weight_tests.py     # 真实 transfer→twist→palm→sanitize 链路数值断言
python3 test/offline/run_complete_tests.py   # 缺骨合成/按侧降级
```

- 合成骨架族：xnalara/bip001/UE4/Daz/garbage 命名 × 原始尺度/微缩/裙发/链内 twist/无锁骨/无趾/四指/六节脊柱/翼。
- 权重场景：UE 侧挂 twist、XNALara 无 twist（reclaim）、Daz 链内 twist；断言**逐顶点守恒、捩骨梯度单调、肘邻接无渗漏、掌骨合成、sanitize 后 ≤4 骨且归一**。
- 重构后全部通过（识别 14/14）。

## 5. 遗留事项（需要远端 Blender 复核）

1. **标定模型回归**：`test/vmd_compare_test.py` 全链路（现 20 步）。预期差异点仅两处，语义上等价或更优：
   - 标定模型若有 unused 名的段上 twist helper，旧版逐顶点最近、新版按段折叠（τ 后分布等价，肘环数值可能有 ≤几 pt 漂移）；
   - 新增 7.8 sanitize（目标 PMX 本就是纯 BDEF≤4，影响应为零或正向）。
2. 真实多来源 XPS 模型抽测（UE/Source/Daz 移植各一）。
3. P1 未做：胸骨对自动改名 左胸/右胸（物理移植友好）、>5 节脊柱多余段权重合并、名字种子映射快路径（bones_renamer 字典）。
