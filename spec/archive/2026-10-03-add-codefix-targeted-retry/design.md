# 设计：add-codefix-targeted-retry

## Context

- 现状：`core/code_fix.py` 回归失败分支重派 `runner.run_code_fix(wt, items, failure_summary=...)`（整批 items）+ 全量 `run_regression`；重试轮 run_id 预生成与进度刷新机制（`_preset_run_id(exclude=...)`）已存在，保留复用。
- 回归命令形态由项目 `verify.yaml` 的 `regression` 段声明（pytest 形态），junit XML 是回归产物（含 file/classname，可用作 nodeid 近似映射源）。
- 失败摘要现状是纯文本 `_failure_summary`；失败明细无结构化落盘。
- 2026-09-24~09-25 审计：重试 8 次 ×（整批 agent ~16min + 全量回归 ~10.2min）≈ 3.4h 浪费。
- 相邻能力边界：`add-regression-auto-fix`（已立项）治理**跨轮**「回归失败 → `regression-` 前缀台账条目、复发重开」；本 SPEC 只治理**批内**重试轮，二者共享失败明细落盘但不共享编排路径。

## Goals / Non-Goals

**Goals:**
- 重试轮只修失败用例相关问题（含修测试本身），只重跑失败用例集
- 轮数上限可配置（缺省 3），轮间累计注入失败明细
- 失败明细结构化落盘，重试与审计共用

**Non-Goals:**
- 不改首轮全量回归门与合回闸门
- 不改失败档案/预算/锁释放语义（耗尽后逐字沿用）
- 不做跨轮台账条目（add-regression-auto-fix 职责）

## Decisions

- **D1 明细落盘 `.fenix/code-review/fix-reg-failures-<run_id>.json`**：结构 `{items: [{nodeid, summary}], source_run_id, created_at}`，从回归 junit 产物提取；nodeid 映射以 junit `classname` **主导**重构（pytest junitxml 的 testcase **不产 `file` 属性**，实测形态 `<testcase classname="tests.test_x.TestFoo" name="test_bar"/>`）：classname 点分模块路径转文件路径（`tests.test_x` → `tests/test_x.py`），余下段作 `::` 类链，末接 `::name`，得 `tests/test_x.py::TestFoo::test_bar`；`file` 属性仅当存在时参与一致性校验。映射判定为「不足以唯一重构 nodeid」（如 classname 缺失或非 Python 模块形态、或同一重构结果歧义）→ 回退全量重试并留日志（fail-closed）；pytest 不产 `file` 属预期形态，MUST NOT 因此判映射失败。替代方案（纯文本摘要）无法支撑子集重跑，故弃。
- **D2 子集回归在门面层实现**：`run_regression` 增可选 `subset_nodeids` 参数；仅当项目命令为 pytest 形态（命令含 `pytest` 且子集非空）时执行子集——**以失败 nodeids 取代命令中的既有收集位置参数**（如 `tests/` 目录），保留非收集类旗标（`-q`、`--junit-xml` 等）；MUST NOT 简单「在命令尾部追加 nodeid」——pytest 多位置参数是收集目标**并集**语义（`pytest tests/ nodeid1` 会收集整个 `tests/` 目录 + nodeid1），追加会使子集静默退化成全量跑。子集为空或项目命令非 pytest 形态时忽略子集跑全量。锁根/执行根语义不变。理由：子集是回归调用方（code-fix 编排）的诉求，不该扩散到 `core.regression` 原语。
- **D3 「修测试」授权进 prompt 契约段**（`agents/code-fix.md`）：明确失败可能是产品缺陷或测试缺陷、agent 自行判定；修测试时产物行加 `fix_scope=test`；同时硬性约束「只修失败用例相关问题，MUST NOT 扩面重做全批」。防白洗配套：明细落盘 + `fix_scope` 标注 + 台账复发重开（add-regression-auto-fix）三重审计。
- **D4 重试循环状态机**：`for attempt in range(1, targeted_retry_max+1)`；每轮先派 run（注入累计明细）再子集回归；`passed` → 走既有合回；耗尽 → 走既有现场即弃分支。首轮与重试轮复用既有 `_preset_run_id`/`write_progress` 机制，进度 phase 沿用 `retrying`（轮次号入文案）。
- **D5 回归门放宽的风险锚定**：定向轮只重跑失败集可能漏检修复碰坏的其他用例。缓解：合回后既有周期回归兜底 + 失败明细落盘供复发追溯（衔接 add-regression-auto-fix 复发重开）。用户已确认该权衡（换取每轮 ~25min → 分钟级）。

## Risks / Trade-offs

- [junit→nodeid 映射失真导致子集跑错用例] → 映射要求精确匹配；classname 不足以唯一重构 nodeid 即回退全量（fail-closed；pytest 不产 `file` 属性属预期，不触发回退，见 D1）
- [agent 借「修测试」白洗真缺陷] → `fix_scope=test` 强制标注 + 明细落盘 + 台账复发重开三重防线
- [定向修复过不了子集以外的隐性破坏] → 周期回归兜底（可接受：现状整批重做同样不保证）
- [targeted_retry_max 配置被设得过大致烧钱] → 配置键带注释约束合理区间（1-5），编排侧对每轮 run 失败（非回归失败）仍按既有 chain_skipped 立即收尾，不进轮循环

## Migration Plan

配置键缺省 3，合入即生效；既有调用点（首轮回归、合回、档案）零改动。回滚 = 配置换 1 + 子集回退路径（等价现状）。
