# 设计：add-codefix-affinity-batching

## Context

code-fix 车道现状链路（每批）：`select_batch`（时间序截前 20）→ 建 worktree → agent run（批内已按 file 分组、组数 ≥2 派子代理并行，波次 ≤4，add-codefix-batch-parallel 落地）→ 批收尾全量回归（`run_regression`，verify.yaml regression 段，主机级 `full-suite.lock`）→ 合回核销。

三个瓶颈锚点（2026-09-26 取证）：

1. `core/code_fix.py` `select_batch`（约 :967）：纯 `first_seen_at` 升序截前 N，无任何文件亲和性——同文件问题拆散多批，批批重复取证。
2. `agents/code-fix.md`（「派发」节）：批内并发「固定上限 4」写死在模板文案；`core/agent_runner/prompt_builder.py` `_build_code_fix_prompt`（约 :1624）是 prompt 组装点，具备占位符注入条件（`{items}`/`{out_path}` 等既有先例）。
3. 批收尾回归恒全量：fenixd 自身口径约 10min/批，是批级最大固定开销；`RegressionSpec.cmd`（`core/verify_contract.py:188`）为 str/list 两态、cwd=项目根，`{port}` 占位符+环境变量双轨先例可循（e10c0e4）。

与其他车道工作的边界：`decouple-codefix-review-lanes`（审查车道连坐/僵死看门狗）、`add-codefix-targeted-retry`（回归失败后的定向重试轮，消费失败用例明细）、`add-mergeback-wip-active-coordination`（WIP 协调）各治一段，本 SPEC 不触碰。

## Goals / Non-Goals

**Goals**

- 同文件条目永同批、同目录文件尽量同批，批数下降摊薄批级固定开销（建树/agent run/回归/合回）。
- 批规模弹性化：`batch_size` 从「精确条数」放宽为「目标规模 T」，硬上限 H=2T 防失控。
- 中间批回归按触碰面定向、末批全量兜底，压缩每批回归时间且不放弃链收尾防线。
- 批变大后批内并行度跟得上（波次上限分档 4/6/8）。

**Non-Goals**

- 跨批流水线并行（批 A 回归时批 B 修复）——触及单飞锁与主机级回归锁的语义重构，另行立项。
- 回归失败归因（全量失败定位到具体历史批）——保持既有失败处置语义，不加机制。
- 台账条目格式、进度 total 口径（done+open）、合回核销路径的任何变更。

## Decisions

### D1 聚类算法：确定性贪心装箱（文件组不可拆）

- 文件组=按 `file` 字段归并的 open 条目集合；组间按组内最早 `first_seen_at` 排序（缺失回退最小 `item_id`），保持与既有选批相同的稳定性口径（同输入同输出，进度读侧与测试可复现）。
- 装箱四规则（详见 spec Scenario）：同目录组浮动吸收至 H；异目录组仅在批 < T 时吸收、吸收后 ≥T 即封批；达 H 封批；单文件组 >H 独立成批不拆。
- 「同目录」取**直接父目录**全等比较——不引入模块/语义相似度（那需要 import 图分析，复杂度失控且误聚类代价是批间串行回归变多）。顶层文件（无父目录）互不同目录。
- **为什么不拆超大文件组**：拆分重蹈「同文件问题分批重复取证」的覆辙；45 条的单文件批虽大，但 agent 批内并行（波次上限 8）可消化，且核销/进度粒度本就是组级。
- 实现落点：`select_batch` 重写为「读台账 → 排除 → 文件组归并排序 → 装箱返回首批」。注意既有调用点只消费**首批**（返回 list 后由链逐批推进、每轮重新调 `select_batch`）——装箱算法天然支持：每次调用返回装箱后的第一个批即可，链推进语义零改动。

### D2 波次上限分档注入

- 分档函数 `min(8, max(4, ...))` 三档：G≤4→4、5≤G≤8→6、G≥9→8（G=批内文件组数，即并行真实粒度）。纯函数实现于 `core/code_fix.py`，单测直测。
- 注入路径：`_build_code_fix_prompt` 计算 G（批次 items 已在 detail 中）→ 渲染 `{wave_cap}` → `agents/code-fix.md` 模板把「固定上限 4」改为「{wave_cap}」占位符引用并写明分档语义。模板是 tracked 文件，`{wave_cap}` 缺失时 prompt_builder 回退缺省 4（模板旧文案兼容）。

### D3 回归两段式：占位符 + fail-open 回退

- `{test_targets}` 占位符：声明在 verify.yaml `regression.cmd` 中，框架替换为空格连接的测试路径列表；对齐 `{port}` 先例（替换 + 同值导出 `FENIX_TEST_TARGETS` 环境变量，str/list 两态 cmd 都支持；list 形态仅替换元素级占位符）。**cmd 无占位符 = 该项目不参与定向化**，恒全量，存量项目零迁移。
- 末批判定：与链收敛出口同口径——`select_batch(root, T, exclude_ids=chain_skipped ∪ deferred_ids ∪ 本批 item_ids)` 返回空（失败档案 ∪ chain_skipped ∪ 延迟台账与本批全部排除后无可选批条目）。MUST NOT 用裸 `count_open_items` 排除本批判定：`count_open_items` 含失败档案/跳过/延迟的 open 条目（`core/code_fix.py:1000` docstring），链最后一批收尾时这些条目常在档，裸计数 >0 会把实际末批判成非末批 → 定向回归 → 链随即正常收敛，全量兜底整链落空。判定必须在核销**前**做（核销会改变 open 集）；链排除集（chain_skipped/deferred）从既有批上下文与延迟台账取得。
- 触碰面映射（纯函数 `_map_fix_files_to_tests`）：规则 (a) 测试文件直接入选；(b) 产品文件 → 同目录 `tests/` 的 `test_<stem>.py` 命名匹配 + `tests/` 树内文本 grep `import <module>`/`from <module>` 反查取并集。stem 取文件名去扩展名（`core/foo.py` → `test_foo*.py` glob）。grep 反查以 `subprocess` 单次 `grep -rl` 完成，MUST NOT 逐文件 Python 遍历（tests/ 树可达千文件）。
- fail-open 哲学：映射空集、cmd 无占位符、配置关闭 → 全量。定向化是优化不是门槛，任何不确定都回退到「多花回归时间」这一侧，MUST NOT 回退到「跳过回归」。
- 定向回归执行仍走 `run_regression`（构造替换后的 RegressionSpec 副本传入），主机级锁、XML 解析、超时全继承——不新增执行通道。
- 失败语义零新增：定向失败 → 既有回归失败路径（定向重试轮，其失败用例注入机制与本 SPEC 正交）；末批全量失败 → 同既有路径。**不**做「定向通过但末批全量失败时归因历史批」的机制。

### D4 配置键与 UI 同步

- `admin.code_review_fix.targeted_regression`：严格 bool、缺省 true、非法回退缺省 + warning（先例：add-code-review-scope-config 两档非法回退）。
- QualityPanel.tsx 的 `code_review_fix` 区块加 Switch（antd），读写走既有 GET/POST `/api/config`；`config.template.yaml` 注释样例同步。遵守「新增配置项必须带 Dashboard 界面」项目约定。

## Risks / Trade-offs

- **中间批定向回归漏检**（改动面跨模块但映射未命中）→ 由末批全量兜底；链中途人工中止时中间批可能带着未全量验证的改动已合回——接受（合回防线从「批批全量」降为「末批全量」，用户已确认此取舍）。
- **聚类导致饥饿**（老文件的异目录小批被新文件的大批挤后）→ 组间排序锚定最早 first_seen_at，仅目录亲和在批内重排，跨批顺序仍近似时间序；排除口径保证失败条目不重复占批。
- **`{test_targets}` 注入的 shell 字符串形态**（路径含空格）→ 本仓库与主流 pytest/jest 项目路径无空格；替换时对路径做 shell 引用包裹，README/注释样例声明该限制。
- **grep 反查误报**（import 名同名不同模块）→ 误报方向是「多跑测试」，fail-open 侧，可接受。

## 人工步骤（不进 tasks 门禁）

- fenixd 自身 `.fenix/verify.yaml`（gitignored 运行时文件，worktree 不可达）的 `regression.cmd` 加 `{test_targets}` 占位符——本 SPEC 落地后在主树人工同步，本仓库方能享受定向化；SPEC 交付 tracked 的 `config.template.yaml` 样例与文档说明。
- daemon 重启使后端改动生效（框架既有部署惯例）。

## Open Questions

（无——分组数值分支、回归两段式语义、配置回退均已在 specs Scenario 定死。）
