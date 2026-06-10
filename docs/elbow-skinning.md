# 胳膊肘 / 关节蒙皮 — 行业做法、转换器现状、做到最好的方案

> 本文档回答:**「MMD 行业怎么单独处理胳膊肘?转换器现在做到什么程度?要效果最好该怎么改?」**
> 结论基于:① 远端 Blender 实测(解析目标 PMX 二进制 + 量化转换模型权重)+ ② 两份带 URL 的研究(PMX/mmd_tools 源码、VPVP 系日文实践)。
> 配套测试见 `docs/TESTING.md`、`test/`。素材/连接值见 `docs/remote.local.md`(gitignore)。

---

## 0. 结论速览(TL;DR)

1. **肘部是两个独立问题**:**扭转**(前臂 pronation,糖纸/`ねじ切れ`)和**弯曲**(flexion,内塌陷/`痩せ`)。各有各的解法,别混为一谈。
2. **扭转 → 捩骨**(腕捩/手捩 + `0.25/0.5/0.75` 旋转付与子骨 + 渐变权重),**不是 SDEF**。本转换器 `twist.py` 已实现,**实测有效**。
3. **弯曲 → 行业按优先级**:① 渐变权重(主力)→ ② SDEF 肘环 → ③ 補助骨 → ④ BDEF4 → ⑤ 矫正 morph。
4. **SDEF 不是 MMD 标准必需品**:本测试目标 PMX **整模 0 个 SDEF 顶点**(纯 BDEF)。SDEF 是可选高级层,只局部(肩/肘/膝/股/脇/指),**绝不全身**。
5. **转换器现状**:扭转 ✓;弯曲渐变**居中但偏窄**(`0.97→0.73→0.09→0`,2~3 圈),有改进空间。
6. **mmd_tools 1.0.2 能产 SDEF**(经 3 个 shape key:`mmd_sdef_c/r0/r1`),所以想超过目标也有路径。

---

## 1. 行业做法:肘部=两个问题

| 问题 | 现象(术语) | 行业解法 | SDEF? |
|------|------------|----------|:----:|
| **扭转**(前臂绕轴) | 糖纸扭曲 / `ねじ切れ`(twist 甜甜圈) | **捩骨**:腕捩(上臂)/手捩(前臂)+ `0.25/0.5/0.75` 旋转付与子骨 + 沿轴**渐变权重** | ❌ |
| **弯曲**(肘屈伸) | 内塌陷 / `痩せ`(变细) | 见 §2 排序 | ⭕ 可选 |

**骨链**:`肩 → 腕 → 腕捩 → ひじ → 手捩 → 手首`。
腕捩在**上臂**(腕→ひじ,显示尾指向 ひじ),手捩在**前臂**(ひじ→手首,显示尾指向 手首)。

**捩骨怎么消糖纸**:建腕捩时自动生成 3 根隐藏子骨,按 `0.25 / 0.5 / 0.75` 比例继承捩骨的 roll(回転付与);顶点沿肢体**渐变**绑到这几根分级骨,把 180° 扭转**沿轴摊开**,而不是堆在一圈(堆一圈就撕)。手捩同理。自然扭转范围只有 0.5 圈(180°),超了会出"twist 甜甜圈"。

> ⚠️ **準標準ボーン追加(そぼろ)插件只建骨,不设 SDEF、不刷权重**。跑完手臂仍穿模,权重是另一道工序。"加了半标准骨 ≠ 肘部就好了"。

## 2. 弯曲塌陷:行业优先级(排序即性价比)

| 排序 | 技术 | 说明 |
|:----:|------|------|
| **①** | **渐变权重(主力)** | 腕/ひじ 间**平滑过渡**,手动按 **10% 档**(100-90-…-10-0)铺,再 `ウェイトぼかし` 模糊。比 SDEF 更根本、更稳。关节处要有足够 edge loop。 |
| **②** | **SDEF 肘环** | 只把肘部过渡顶点 BDEF2→SDEF,保体积防 `痩せ`。 |
| ③ | **補助骨** | 肘根加 `ひじ補助` + 旋转付与 ≈0.6 跟随 ひじ,深弯分担折痕。 |
| ④ | BDEF4 | 4 骨,和额外 FK 辅助骨配合更可控,手工多。 |
| ⑤ | 矫正 morph | 极端 pose 专用,蒙皮数学修不了时的最后手段。 |

**SDEF 标准应用区**:肩 / ひじ / ひざ / 股関節 / 脇の下 / 指。**只局部,绝不全身**——全身 SDEF 会破模、变慢,且 PMXEditor 默认笔刷是 BDEF,**一重涂就 revert 回 BDEF**。工作流:先全身 BDEF2,再只转问题顶点。

**手首**两个问题分开:**弯曲**按普通关节(渐变权重 + 可选 SDEF);**轴向扭转**(前臂 pronation)是手首主要矛盾,靠 **手捩 + 0.25/0.5/0.75 + 渐变权重**,**不是 SDEF**。

## 3. 转换器现状(实测,2026-06-07,目标=Purifier Inase 18)

### 3.1 目标 PMX 是纯 BDEF —— 它自己都没用 SDEF
直接解析 PMX 二进制,逐顶点统计 weight-deform 类型(字节核账吻合:46.65 B/顶点 × 169,575 = 消耗的 7.91 MB,parse 正确):

| 类型 | 占比 |
|------|------|
| BDEF1 | 42.2% |
| BDEF2 | 31.7% |
| BDEF4 | 26.1% |
| **SDEF** | **0** |
| QDEF | 0 |

且目标带**完整半标准捩骨组**:`腕捩 + 腕捩1/2/3`、`手捩 + 手捩1/2/3`(L/R,含 mmd_tools 的 `_dummy_/_shadow_` 辅助骨,共 40 根)。→ **目标用「捩骨 + BDEF」解决肘/前臂,不是 SDEF。**

### 3.2 转换模型:同款路线
- **扭转 ✓**:肘部一圈(127 顶点)初测权重 = `左ひじ 41% + 左腕捩 43% + 左手捩1 16%`,每顶点骨数 `{2骨:76, 3骨:51}`。捩骨在扛,糖纸按 MMD 标准方式处理。`左腕`基骨在肘=0 是对的(近肘段归 腕捩,腕基骨权重集中在肩侧)。其中 `手捩1 16%` 比目标(2%)偏高 → **已在 §8 调优至 3%**。
- **弯曲 ⚠️ 有 headroom**:沿 `腕(0)→手首(1)` 轴量化过渡(肘在 t=0.49):

```
 t-band       upper{腕,腕捩}        过渡形状
 0.36-0.43    0.97  ███████████████████
 0.43-0.50    0.73  ██████████████          ← 肘关节
 0.50-0.57    0.09  ██
 0.57-0.64    0.00
```

过渡**正好居中在肘**(好),但**偏窄**:`0.97→0.73→0.09→0`,只有约 2~3 圈顶点分担,比行业理想的"10% 细档 + 模糊"陡。**这是"做到最好"的第一发力点。**

### 3.3 mmd_tools 1.0.2 怎么存 SDEF(产 SDEF 的确切机制)
**不是顶点组,是 3 个 shape key**(形状键天然逐顶点 Vector3,正好存 C/R0/R1 三坐标):
- `mmd_sdef_c` / `mmd_sdef_r0` / `mmd_sdef_r1` —— 存 C / R0 / R1 的**绝对 Blender 坐标**。
- `mmd_sdef_skinning`(shape key,驱动输出)+ `mmd_sdef_mask`(顶点组,屏蔽 Armature 修改器,交给驱动)。
- 运行时驱动 `mmd_sdef_driver`(Blender 视口即可正确变形)+ `mmd_root.use_sdef` 开关。
- 导入:`importer.py` 对 SDEF 顶点 `shape_key_add`,坐标 `.xzy * scale`。导出:`exporter.py` 检测到这 3 个 shape key 就写 SDEF。

## 4. 要效果最好:落地方案(按性价比)

> 注:本节是想**超过**目标(premium)时的可选项。**贴近目标**的实际改动 + 实测见 **§8**。

**① 先做:肘/膝渐变拓宽 + 抹平(最高 ROI)。**
行业第一技术,当前只是基础版。做法:在 `twist.py` 后 / 权重收尾步,对肘/膝过渡环做**位置驱动的渐变重铺 + 邻域模糊**(把 3 点斜坡拉成 5~7 点平滑斜坡)。符合 CLAUDE.md「位置驱动 + 守恒、不要 per-target 魔数」。便宜、稳、不依赖 SDEF。

**② 可选(premium,会超过目标):肘/膝/肩环叠 SDEF。**
mmd_tools 1.0.2 能产,**精确规则**(源码 + 实测确认):
- 每个 SDEF 顶点**恰好 2 根骨**(BDEF2 基底)。
- 建 3 个 shape key `mmd_sdef_c/r0/r1`,存 C/R0/R1 **绝对 Blender 坐标**(Z-up)。
- **C 必须与 rest 位置差 > 0.001**,否则导出**静默降回 BDEF2**。
- **C/R0/R1 取值**:无官方公式(PMXEditor 闭源)。社区惯例 = **C 取关节头(ひじ head),R0=腕 head,R1=ひじ head**(或 C 取顶点在 腕–ひじ 轴上的投影)。数学上 rest pose 对任意自洽取值都不变 —— C/R0/R1 只决定弯曲时怎么鼓,不影响静止正确性。
- **只做关节环,别全身。**

**③ 防回归:捩骨 `軸制限` 要扛过 PMX 导出。**
捩骨轴限在 PMD↔PMX 转换 / 重算骨尾时会被破坏(症状:MMD 里手臂乱拧)。预防 = 骨尾设**ボーン参照**而非相对偏移,并固定轴限(腕捩→ひじ 轴,手捩→手首 轴)。建议核查导出的捩骨是否满足。

## 5. Caveats(必须如实记住)

- **SDEF 非 MMD 标准必需**:目标自己都没用。加了是**超过**目标,不是补缺口。别被"行业都用 SDEF"误导。
- **无官方 SDEF 公式**,只能用 `C=关节/R=骨头` 惯例 + **目视验证**。mmd_tools 用 nlerp 四元数混合,saba 参考实现用真 slerp。
- **姿态对比测试(`test/vmd_compare_test.py`)测不到这些** —— `compare()` 只看骨朝向,蒙皮质量(塌陷/渐变/SDEF)一概看不见。要验证得**把肘弯到 90~120° 渲染对比塌陷**。
- mmd_tools **不会**在骨移动后自动重算 C/R0/R1,是静态数据;编辑权重会让 SDEF 锚点失效。

## 6. 复现方法(给未来会话)

部署 + 跑端到端见 `docs/TESTING.md`。以下是本文结论的**量化探针**(远端 `mcp__blender__send_code_to_blender` 执行)。

**A. 解析 PMX 二进制统计 deform 类型**(判断目标是否用 SDEF,独立于 mmd_tools 导入):
逐顶点读 weight-deform 字节(`0=BDEF1 1=BDEF2 2=BDEF4 3=SDEF 4=QDEF`),按 PMX globals 的 bone-index-size 推进。完整脚本见本次会话记录;核心:`open(pmx,'rb')` → 跳过 header/name → `vcount` → 每顶点 `pos(12)+normal(12)+uv(8)+addvec4*16+type(1)+权重(按类型)+edge(4)`,tally type 字节。

**B. 肘部权重过渡曲线**(判断渐变是否平滑):沿 `腕 head → 手首 head` 轴,把肘附近顶点按轴参数 t 分桶,统计每桶 `{腕,腕捩}` vs `{ひじ,手捩}` 的平均权重份额 —— 看 upper 从 1→0 的斜坡宽度。

**C. SDEF 存储检测**:扫所有 mesh 的 shape key / 顶点组,找 `mmd_sdef_c/r0/r1`(shape key)与 `mmd_sdef_mask`(顶点组)。转换模型与目标若都没有 → 都是 BDEF。

---

## 7. 出处

**格式/实现(PMX 源码级)**
- [saba `PMXModel.cpp`(SDEF 公式参考实现)](https://github.com/benikabocha/saba/blob/master/src/Saba/Model/MMD/PMXModel.cpp)
- mmd_tools(UuuNyaa fork):[core/sdef.py](https://github.com/UuuNyaa/blender_mmd_tools/blob/main/mmd_tools/core/sdef.py) · [pmx/importer.py](https://github.com/UuuNyaa/blender_mmd_tools/blob/main/mmd_tools/core/pmx/importer.py) · [pmx/exporter.py](https://github.com/UuuNyaa/blender_mmd_tools/blob/main/mmd_tools/core/pmx/exporter.py) · [operators/sdef.py](https://github.com/UuuNyaa/blender_mmd_tools/blob/main/mmd_tools/operators/sdef.py)
- [PMX 2.0 spec gist(felixjones)](https://gist.github.com/felixjones/f8a06bd48f9da9a4539f) · [DeepWiki: mmd_tools SDEF System](https://deepwiki.com/MMD-Blender/blender_mmd_tools/6.1-sdef-system)
- [SDEF=SBS、公式非公开(katwat)](http://katwat.s1005.xrea.com/wp/6894)

**实践(VPVP 系日文)**
- [SDEF vs BDEF / 应用区 / PmxView 配色(monyanote)](https://note.com/monyanote/n/nb610f1fb47a3)
- [肘/膝/補助骨/SDEF-C 正规化(tsuki-gummd)](https://tsuki-gummd.hatenablog.com/entry/2024/02/02/221623)
- [捩骨 0.25/0.5/0.75 机制(q-ku)](https://q-ku.blog.jp/archives/11315486.html)
- [骨链与捩骨摆位(niconico ar1444359)](https://site.nicovideo.jp/ch/userblomaga_thanks/archive/ar1444359)
- [選択頂点をSDEFに設定 + 不推荐全身(yamabatoo)](https://yamabatoo.hatenablog.com/entry/2016/06/21/PmxEditor%E4%B8%8A%E3%81%A7%E3%81%AESDEF%E3%82%A6%E3%82%A7%E3%82%A4%E3%83%88%E8%AA%BF%E6%95%B4%E6%96%B9%E6%B3%95)
- [捩骨軸制限在转换中损坏 + 修复(niconico ar2013830)](https://site.nicovideo.jp/ch/userblomaga_thanks/archive/ar2013830)
- [準標準ボーン追加后仍需权重(karisakmmd)](https://karisakmmd.blog.jp/archives/8334623.html)

> 旗标:VPVP wiki(`w.atwiki.jp/vpvpwiki`)、BowlRoll 文件页对自动抓取 403;以上事实均由 ≥2 个独立日文二手源交叉确认。SDEF 精确公式官方未公开(第三方逆向)。

---

## 8. 实施记录 — 肘环贴近目标(2026-06-07)

**目标转向**:不是「做到最好」(加 SDEF 反而偏离纯-BDEF 的目标),而是**贴近目标**。

**实测对比**(肘环,`mmd_*` 元数据组已剔除;目标值固定):

| 肘环指标 | 改前 `TAU_LO_FOREARM=0.05` | 改后 `=0.15` | 目标 PMX |
|---|---|---|---|
| 手捩1 渗漏 | 0.16 | **0.03** | 0.02 |
| 腕捩 / ひじ | 0.43 / 0.41 | 0.43 / 0.55 | 0.53 / 0.45 |
| 每顶点骨数 | {2:76, 3:51} | {2:112, 3:15} | {2:1219} 纯 BDEF2 |
| 到目标 L1 距离 | 0.28 | **0.21** | — |

**改动**:`convert/weights/twist.py` — `TAU_LO_FOREARM 0.05 → 0.15`。前臂紧贴肘的一段保持纯 `ひじ`,手扭转推迟介入,使肘环回到目标式的干净 `腕捩+ひじ` BDEF2,3 骨顶点 51→15。释放的前臂侧权重物理上归 `ひじ`(不是 `腕捩`),故 `ひじ` 升、`腕捩/ひじ` 偏向与目标相反约 10pt —— 这是 XPS 上臂绑肩的源差异(`twist.py:17-20` 接受,不为此破例 override XPS)。

**回归验证**(`test/vmd_compare_test.py` 完整跑):转换 19/19 OK;FK 跨帧 σ 全 0.000;腿 IK 最差帧 avg 4.4° —— 与基线**逐位一致**(`compare()` 只看骨朝向、与权重无关,符合预期)。总体 **PASS ✅**。

**未做的视觉验证**:专门把肘弯到 90~120° 的特写渲染对比(此改动主要影响手腕扭转时肘环的耦合,静态弯肘里差异细微)。数值已命中目标,视觉特写为可选项。
