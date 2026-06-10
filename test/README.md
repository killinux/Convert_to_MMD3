# test/ — 验证

## offline/ — 离线单元/集成测试（无需 Blender）

合成骨架族 + fake_bpy 驱动**真实插件代码**（识别/分类/权重链/补全），是改这些模块的回归门：

```bash
python3 test/offline/run_identify_tests.py   # 14 命名/结构变体的识别矩阵 + 分类器断言
python3 test/offline/run_weight_tests.py     # transfer→twist→palm→sanitize 数值断言（守恒/梯度/折叠）
python3 test/offline/run_complete_tests.py   # 缺骨合成与按侧降级
```

背景与设计见 `docs/any-xps.md`。

# 端到端验证（远端 Blender）

`vmd_compare_test.py`：XPS → MMD 一键转换 → 与参考 PMX 并排 → 套同一 VMD → 数值对比 + 渲染对比图。
一条命令复现整套验证，PASS/FAIL 自动判定。

## 跑法

**A. 通过 BlenderMCP（Claude / `send_code_to_blender`）**
把 `vmd_compare_test.py` 整段内容发给 `mcp__blender__send_code_to_blender`，文件末尾的 `run()` 会自动执行。

**B. 在 Blender 文本编辑器里**
打开 `vmd_compare_test.py` → Run Script。

**C. 作为插件子模块**
插件已装到 `scripts/addons/Convert_to_MMD2/` 时：
```python
import Convert_to_MMD2.test.vmd_compare_test as t
t.run()
```

## 改素材：只动顶部 CONFIG

```python
SRC_XPS = r"E:\mywork\mymodel\inase (purifier)_lezisell-A\xps-b.xps"   # 源 XPS（绝对路径）
TGT_PMX = r"E:\mywork\mymodel\Purifier Inase 18\Purifier Inase 18 None.pmx"  # 参考 PMX
VMD     = r"E:\mywork\mymodel\yaoxiang\yaoxiang.vmd"                    # 动作 VMD
OUT_DIR = r"E:\mywork"                                                  # 对比图输出目录
```
> 都是**远程 Windows Blender 上的绝对路径**。换机器/换模型时只改这几行。
> 若不想把真实路径提交到仓库，可把 CONFIG 抽到一个 `test/paths.local.py`
> （`.gitignore` 已忽略 `*.local.*` 模式中的 local 文件，按需扩展）。

## 流程（run() 依次调用）

| 步 | 函数 | 做什么 |
|----|------|--------|
| - | `check_files` / `clean_scene` | 校验三个素材存在；清空场景 |
| 1 | `import_xps` | XNALaraMesh 导入 XPS（→ 骨架 `Armature`，109 骨/8 网格） |
| 2 | `convert` | `object.one_click_convert` 一键转换（→ 196 骨，隐藏备份骨架） |
| 3 | `import_pmx` | mmd_tools 导入参考 PMX（scale=1.0） |
| 4 | `scale_and_place` | 按身高比放大转换模型到等高，并排、脚底对齐 z=0；返回缩放比 |
| 5 | `import_vmd` | 干净一次性导入 VMD：PMX scale=1.0，**转换模型 scale=1/缩放比** |
| - | `compare` | 关键骨世界向角差，PASS/FAIL 判定 |
| - | `render_compare` | 渲染 `compare_f*.png`（左=PMX 右=转换） |

## 判定标准

- **FK（手臂/手指/躯干）**：每根骨的世界向角差应**跨帧恒定**（σ < `FK_CONST_TOL`=0.05）。
  恒定即证明 VMD 给两边施加的是**相同的局部旋转**；那个非零常数只是两套骨架 rest 朝向（骨尾绘制方向）不同，不是姿态差。
- **腿部（IK）**：各帧平均世界向角差 < `LEG_AVG_TOL`=10°。

最近一次结果：**PASS** — FK σ 全 0.000；腿部最差帧 avg 4.4°。

## 关键坑（已固化进脚本，别再踩）

1. **VMD 导入尺度**：转换模型是「米」尺度（身高 ~1.7），PMX 是 MMD 原生大单位（身高 ~20）。
   给转换模型导 VMD **必须用 `scale = 1/缩放比`（≈0.084）**，否则 IK 腿崩到 60~100°。
   FK 旋转与尺度无关，所以手臂/手指不受影响——只有依赖目标位移的 IK 腿会炸。
2. **一次性导入**：从干净场景按正确 scale 一次导入。先 1.0 再清空重导会污染足IK首帧（出现 -13.7 异常，开头 8 帧腿偏 ~89°）。
3. **骨名映射**：转换模型 MMD 名在 `bone.name`（如 `左腕`）；PMX 在 `mmd_bone.name_j`。对比时分别取。
4. **比例差 ≠ 姿态差**：两角色骨架本身比例差 ~17%（rest 静止即如此），归一化关节位置会差 ~19%，那是体型不同，不是动作错。
