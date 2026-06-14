# inase 下半身塑形 & 头发误绑 修复（Fable5 MMD3 回归）

> 2026-06-14。修复 commit 见本提交。标定模型 inase（`xps.xps`，Rise of Eros / Purifier）。

## 背景

MMD3（"Convert to MMD 3"，Fable 5 泛化重构，基线 `30bda66`）相比 MMD2（Opus 4.8，`tag baseline-good-2026-06-14` @ `3282aa8`）在标定模型 **inase** 上有两处回归，远端 Blender 3.6.15 + yaoxiang.vmd 实测确认：

1. **下半身**：大腿/臀塑形丢失 —— VMD 动作下大腿根→髋的过渡塌陷、扁平（MMD2 饱满）。
2. **头发**：约 10–15% 发束权重绑到了「下半身」骨 —— 头一动这些头发跟着盆腔跑、乱翘支棱。

两处的共同病灶：inase 是**游戏 rig**，有「根骨兜底权重」——`unused bip001 pelvis` 绑了大腿根过渡皮（≈210），全局根 `root ground` 兜底绑了头发等远处皮（≈1713）。Fable 5 重构对这两类根骨皮用了**"按骨的角色标签一刀切"**的粗暴规则，对 inase 不成立。

## 根因

### 根因 1 — 下半身主骨选择（`skeleton_identifier.py` `_map_spine`）

MMD3 把 leg-fork 骨（`bip001 pelvis`）**直接**设成下半身主骨（`result["lower_body_bone"] = chain[leg_idx].name`）。于是大腿根权重从 MMD2 的"经 pelvis-helper **位置驱动转移**、形成 2–4 骨平滑过渡"退化成"硬绑下半身 1–2 骨" → 大腿/臀塑形塌。

> 注：MMD3 这么改本是为泛化——注释写"防止有权重的 pelvis 被当 センター、被 control-bone cleanup 抹皮（legs hang off 'spine lower' 的 rig）"。所以它是个 **trade-off**，不能无脑 revert。

### 根因 2 — 控制骨皮归属（`convert/weights/transfer.py`）

`transfer` 把控制骨（`CONTROL_BONES = 全ての親 / センター / グルーブ / 操作中心`）的皮**无条件塞给「下半身」**（`pool = '下半身'`），假设"控制骨皮 = 盆腔皮"。这对 センター 成立，但对**全局根 全ての親**（= `root ground`，兜底绑了头发）是错的。根因 1 修复改变识别格局后（`root hips → センター`），这条无脑规则就把头发的 root-ground 皮塞给了下半身。

## 修复（一律位置驱动，符合 CLAUDE.md）

### 修复 1 — `_map_spine` 兼顾版

```python
if leg_idx is not None:
    if (leg_idx > 1
            and len(chain[leg_idx - 1].children) == 1
            and abs(chain[leg_idx - 1].head_local.x) < lat_eps):
        result["center_bone"] = chain[leg_idx - 1].name   # 父(root hips)→センター
    else:
        result["lower_body_bone"] = chain[leg_idx].name   # 无父→pelvis当下半身(防抹皮)
```

有合格的**居中单子父骨**（如 inase 的 `root hips`）→ 父当 センター、`bip001 pelvis` 留作 pelvis-helper（权重位置驱动摊给下半身，恢复 2–4 骨过渡）；无父骨 → 保持 Fable 5 的 pelvis→下半身。**两全**。阈值用 `lat_eps = H * CENTER_EPS`（尺度无关）。

### 修复 2 — 控制骨皮按 nearest（`transfer.py`）

删掉 `if ubone.name in self.CONTROL_BONES: pool = '下半身'`，让控制骨的皮**落到下面的 per-vertex nearest 分支**（`min(valid_heads, key=距离)`）：头发→頭（最近）、盆腔皮→下半身（最近）。位置驱动、无 per-target 魔数。

## 验证

| 项 | 修复前 MMD3 | 修复后 | MMD2 基线 |
|---|---|---|---|
| 大腿中段每顶点骨数 | 1–2 骨 | **2–3 骨** | 2–4 骨 |
| 大腿 下半身过渡权重 | 0 | **3.2** | 3.2 |
| 头发 绑下半身权重 | 1815 | **0** | 0 |
| 前臂肘弯角 | 0° | **0°** | 0° |
| 离线 identify / weight / complete | — | **19/19 + ALL PASS** | — |

## 踩的坑（诊断弯路，引以为戒）

这次诊断绕了远路，几个假设全被实证推翻——记下来别再犯：

1. **rest 视觉误判**：一开始看 rest 渲染图判断"前臂在肘部弯折"，实测前臂骨夹角 **0.0°**（标准 A-pose）——把 45° 斜下的 A-pose 误当肘弯，还脑补了左右差异。**教训：先量数据（骨角度）再信眼睛。**
2. **Workflow 的 shape-key 根因被证伪**：多 agent workflow 纯代码推断根因是"`_bake_pose_delta_to_rest` 跳过带 shape-key 的网格、骨改直皮没跟"，但远端实测 inase 网格 **0 个 shape key**——根因错，patch 还依赖两个未实现的 helper。**教训：纯代码推断必须落到 Blender 实证。**
3. **sanitize 假设被证伪**：怀疑 Step 7.8 sanitize（剔渣 <0.5% / 限 4 骨）削了大腿塑形细分，monkeypatch 跳过 sanitize 重测——大腿**没**恢复（仍 1–2 骨）。**教训：动刀前先 monkeypatch 实验证伪/证实，别照推断改。**
4. **修一处害一处（红线）**：下半身修复（改 `_map_spine`）连累了头发（误绑下半身 1815）——正是 CLAUDE.md / memory 反复警告的"**通用改动极易帮一个害另一个；inase 标定不可回归**"。当时看大腿修好 + 离线过 + 前臂没破坏就乐观了，**漏查头发**；是用户"头发还有问题"抓到的。**教训：改完做全身体检（下半身/头发/手臂/手全测），不只看修的地方。**
5. **坐实方法**：每个结论都用 **远端实测权重 / monkeypatch / git-stash 修复前后对比** 坐实，再下刀。例：git stash 回原版重转换，确认头发回归是修复引入（修复前绑下半身 0、修复后 1815）。

## 相关

- MMD2 好基线：`~/claudework/convert/Convert_to_MMD2` @ `3282aa8`（`tag baseline-good-2026-06-14`）
- 转换步序、远端部署、看图（base64 落盘抢救）：见 `docs/TESTING.md`、`docs/any-xps.md`
