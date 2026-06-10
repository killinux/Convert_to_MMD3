# 重构读改清单（2026-06-10 会话记录）

> 本文记录「任意 XPS → MMD 泛化重构」会话中**读过什么、改过什么、为什么改**。
> 设计与调研结论见 [`any-xps.md`](any-xps.md)；对应提交：`975379c`（重构落地）→ `92e10ff`（真实模型验证轮）。

## 一、通读内容（重构前全量梳理）

| 范围 | 内容 |
|---|---|
| 全部源码 | `skeleton_identifier.py` / `helper_classifier.py` / `bone_map_and_group.py` / `bone_utils.py` / `presets.py` / `properties.py` / `ui.py` / `encoding_patch.py` / `__init__.py`，`convert/` 全部（pipeline/identify/correct/rename/complete/align/ik/groups/grants/mmd_convert/semistandard），`convert/weights/` 全部（common/transfer/chain/twist/palm） |
| 文档与测试 | `README.md`、`CLAUDE.md`、`docs/TESTING.md`、`docs/elbow-skinning.md`、`test/README.md`、`test/vmd_compare_test.py` |
| 28 个预设 | `presets/*.json` 全部汇总成命名约定矩阵（哪些体系缺锁骨/趾骨、脊柱几节、Daz 的链内 Bend/Twist 等），作为合成测试的依据 |
| 外部调研 | XPS 格式（GLLara 文档）、XNALaraMesh 导入器源码、mmd_tools exporter 源码、準標準ボーン社区实践、各游戏引擎骨架命名（来源列表见 any-xps.md §1） |

梳理产出：硬编码假设清单（绝对米阈值、`unused*` 前缀依赖、complete 的硬索引 KeyError、importer 合成 tail 不可信等），全部进入 any-xps.md。

## 二、新建文件

| 文件 | 作用 |
|---|---|
| `convert/weights/fold.py` | **折叠决策引擎**（纯几何、无 bpy、可离线测试）：helper 骨权重质心 → 宿主肢段（上臂/前臂/掌）→ 段池骨（腕/ひじ/手首）。覆盖三种 twist 拓扑：UE 侧挂 `*_twist_*`、Daz 链内 Bend/Twist、Source 程序骨残留 |
| `convert/weights/sanitize.py` | **权重收尾**（管线步 7.8）：剔除 <0.5% 残渣 → 每顶点保留最大 4 骨 → 归一化。动机：XPS 输入可非归一/超 4 骨；mmd_tools 导出只做盲 top4 截断无阈值（源码确认） |
| `test/offline/mathutils.py` | 纯 Python `Vector` 替身（本机 pip 编译 mathutils 失败） |
| `test/offline/fakes.py` | FakeBone/FakeArmatureData（data-bone 与 edit-bone 双表面） |
| `test/offline/fake_bpy.py` | 最小 bpy 替身（vertex_groups 含 Blender 式删除重排索引），让**真实插件代码**离线跑 |
| `test/offline/synth.py` | 参数化合成人形骨架：5 命名族 × 结构变体（脊柱节数/锁骨/趾骨/三种 twist 拓扑/裙发翼胸/矫正骨/跖骨/肩挂脖根/居中 pelvis 直通…） |
| `test/offline/run_identify_tests.py` | 识别矩阵（19 用例 × ~30 角色）+ 分类器断言 |
| `test/offline/run_weight_tests.py` | 真实 transfer→twist→palm→sanitize 链路数值断言（守恒/梯度单调/折叠/掌骨合成/≤4骨归一） |
| `test/offline/run_complete_tests.py` | 缺骨合成与按侧降级断言 |
| `docs/any-xps.md` | 调研结论（带来源）、重构前失败矩阵、架构设计、真实模型验证记录、遗留事项 |
| `docs/refactor-changelog.md` | 本文 |

## 三、重写/修改文件

### `skeleton_identifier.py`（核心重写）
- **尺度无关**：所有几何阈值改为骨架高度 H 的比例（0.006H≈旧 0.01@1.7m，米尺度行为不变）。修复：0.17m 微缩模型识别全灭。
- **fork 验证**：腿 fork 须两侧有腿证据（落差>0.22H+弧长+足部转折加分）、臂 fork 须两侧有手部签名（3+ 指链）→ 裙/翼/大衣链偷不走 fork。
- **fork 扫描范围**放开到链尾前一节 + 「fork 之上仅剩头 ⇒ fork=首、上半身2=fork 下一节」语义。修复：rouffe 肩挂 `head neck lower` 手臂全空。
- **`_lateral_candidates`**：直接侧向孩子 + 居中孩子按孙辈所及的**每一侧**提升。修复：tifa `hip→pelvis→双腿` 只进 left 列表导致腿 fork 丢失；rouffe 贴脊柱的肩根。
- **腿 fork 骨 → 下半身**（原先给センター）：センター 是无权重控制骨，由 complete 新建；带臀部权重的 fork 骨改名 下半身 权重原地正确。修复：rouffe 腿挂 `spine lower`（下背权重大户）被当控制骨清权重 → 下半身/腿大面积变形。
- **臂链分段**：经典 4 节链恢复位置映射（永远正确）；评分只用于 >4 节（跳过链内 twist）与 3 节歧义链，去掉有害的弯角加分。修复：inase 短锁骨被评分误判成上臂。
- **腿链关节分段** `_segment_leg_chain`：踝=首个 z<0.12H 节点、膝=髋踝高度中点（twist 名减分）、腿根=膝上最近的「大腿/小腿长度比合理」节点。修复：tifa 前导矫正骨 `c_thigh_b.l` 错位整条腿。
- **趾骨前方约束**：足先EX 候选须在脚踝前方 >0.02H，否则沿链后找。修复：Daz `lMetatarsals` 贴脚跟 → 足首 退化向量（reika 119°）。
- **手指**：拇指=「方向最偏 + 根最贴腕」联合评分；其余指沿掌横向轴排序。修复：所有命名族的中/薬/小指错位。
- 名字仅作低权重 tie-breaker（twist/elbow 关键词），garbage 命名照样识别。

### `helper_classifier.py`（重写）
- 阈值尺度相对化。
- **物理链判定**：深度≥3 且子树**不含 mapped 骨**且**不沿臂段走向** → 整链 preserve 并向下传播（裙/发/尾/饰带保住物理候选）。「子树含 mapped」排除 Daz 链内 twist（可折叠）；「沿臂段走向」区分 foretwist 链（折叠）与袖饰带（preserve）。
- pelvis 锚点改用 下半身（center 作预设回退）；**fork 上方居中祖先 helper**（root hips、unused trash 等）归 pelvis → 权重并入下半身。

### `convert/weights/transfer.py`（重写）
- 决策阶梯：deltoid 斜坡（标定常量逐字保留）→ **段折叠**（名字无关，classifier 标 twist 的段上 helper 全消费，不再只认 `unused*`）→ 逐顶点最近（旧路径保留给脊柱 merge/杂项 unused）。
- 控制骨（センター/グルーブ等）残留权重并入 **下半身** 组（原先逐顶点最近乱洒）。
- 权重质心一次计算共用于 deltoid 检测与折叠规划；骨名解析兼容 rename 前后。

### `convert/complete.py`（重写）
- **绝不 KeyError**：缺 首↔頭 互相合成、缺 肩 从胸/腕几何合成（无权重锁骨）、缺趾 足先EX 合成在脚踝正前地面（不再信 importer 合成的 足首 tail）。
- 手臂/腿**按侧独立**降级（缺一侧只跳过该侧并打印说明）。
- 通用化 pelvis 残留骨挂接（不再只认 `unused bip001 pelvis` 一个硬编码名）。

### 其余修改
| 文件 | 改动 |
|---|---|
| `convert/identify.py` | ①识别前若骨架对象带旋转/缩放先 apply；②**槽位全量写入含空值**（修跨模型残留污染——连续转第二个模型时上一模型的 props 泄漏）；③打印不再回退 scene props |
| `convert/ik.py` | 按侧降级（缺一腿不再中止管线）；无腿提前返回时回 OBJECT 模式 |
| `convert/groups.py` | `pose.group_add` 前确保 POSE 模式（上一步可能停在 EDIT） |
| `convert/pipeline.py` | 新增步 7.8 `object.sanitize_weights` |
| `convert/__init__.py` | 注册 `OBJECT_OT_sanitize_weights` |
| `convert/weights/__init__.py` | 模块说明更新（fold/sanitize） |
| `ui.py` | 次标准页加「权重收尾」按钮 |
| `README.md` | 「任意 XPS 泛化」章节 + 流程图/目录树更新 |
| `CLAUDE.md` | 权重处理原则补充（fold 原则、不信 tail/roll、阈值取 H 比例）、离线测试命令 |
| `docs/TESTING.md` | 期望步数 19/19 → 20/20 |
| `test/README.md` | 离线测试套件说明 |

### 刻意不动的部分
- twist τ 曲线 / reclaim / palm / debleed 的全部标定常量逐字保留。
- 管线步序与全部 `bl_idname` 不变（仅新增 7.8 一步）。
- 大腿/臀部 helper 维持 preserve（变形等价、保留物理二改余地）。

## 四、验证结果

- **离线**：19 识别用例 + 权重链 3 场景 + 补全 5 场景全绿（`python3 test/offline/run_*_tests.py`）。
- **本机 Blender 3.6.21 真机端到端**（与各自参考 PMX 并排 + yaoxiang VMD）：
  - inase（标定）**PASS**（20/20 步，FK σ 全 0，腿 2.9°，优于远端基线 4.4°）
  - Tifa（Daz+矫正骨）**PASS**（腿 5.2°）
  - Reika（Daz）**PASS**（腿 6.9°）
  - rouffe（XNALara 魔改）：识别/权重/腿全对，手臂 FK σ 3-8° 遗留（见 any-xps.md §6）
- 重构前基线：合成识别矩阵 **1/14 通过** → 重构后 **19/19**。
