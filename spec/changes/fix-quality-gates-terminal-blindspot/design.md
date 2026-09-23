# fix-quality-gates-terminal-blindspot 设计

## Context

实证取证（2026-09-23，spec `add-code-fix-batch-failure-selfheal`，pushed，门禁 4/6）：

- 车道产物 `.fenix/verify-progress/add-code-fix-batch-failure-selfheal/code-review.json`：`status=completed`，指纹 `(fenix/...-1790100982, e9c32e80, 4d0501f3)`；merge-back（ab54b8c4）后 `git merge-base <branch> main` = `4d0501f3`（分支尖自身）→ `_lane_fingerprint_ok` 的 merge_base 比对必然失配 → 产物不可见 → code-review 门 pending。结构性必现：merge-back 成功即 merge-base 前移到分支尖，任何 pushed spec 该门恒 pending。
- `.fenix/regression/last-run.json`：指纹 `(main, f19a252, f19a252)`，main 已前进 25 提交至 `1377cd35` → 产物不可见；quality-gates.json 无 full-suite 键（add-impl-selfcheck-model-probe 3.1 后实现者默认不写）→ full-suite 门 pending。

## Goals

- pushed/done/verified 终态 SPEC 的 6 道门禁全部呈现确定性终态（无恒 pending 误导）。
- 不放宽任何真实拒采信语义：修复轮 head 前移仍拒 stale；非终态数据源优先级与逐字节行为不变。

## Decisions

### D1：merge-back 豁免用构造性判据，不用状态枚举

`_lane_fingerprint_ok` 增加分支：当前指纹 `merge_base == head_commit` 时跳过 merge_base 比对。

- 判据 `merge-base(branch, main) == rev-parse(branch)` 数学上等价于「分支尖是 main 的祖先」= 分支已完整合入，不依赖 STATE 状态字段（避免状态与 git 事实漂移时的双真源问题，参照 status-modal ready 限定过时的教训）。
- 豁免只跳过 merge_base 一项；branch/head_commit 全等仍强制——head 前移（修复轮重审场景）照旧拒采信。
- 非豁免路径（分支未合入）行为逐字节不变。

### D2：full-suite 终态豁免为最高优先级 + 固定文案

`_full_suite_status` 首行加终态短路：`spec_status ∈ ("verified", "done", "pushed")` → `(skipped, "SPEC 已终态，全量回归跟踪移交主树")`。

- 优先级高于框架产物源：终态显示语义必须确定性，不随 main 推进/回归重跑摆动（用户决策「终态豁免显示」的本意）。
- 终态集合与 `_FRAMEWORK_PASSED_STATUSES` 有意不同：implemented/testing 仍在流水线内（可能修复轮、回归重跑），显示实时状态；verified 起进入收尾，回归跟踪责任移交主树。
- skipped 计入 done（既有语义：已了结），前端「不适用」样式已支持，零前端改动。
- reason 文案在模块内固化为常量（键名/文案固化惯例，禁止同义改写）。

### D3：测试锚定真实指纹形态

用例注入真实形态的指纹三元组（嵌套 `fingerprint` 子对象，对齐 run_impl_ocr 写侧），覆盖：merge-back 采信、head 前移拒采信、未合入 merge_base 失配拒采信、终态豁免、终态豁免优先于产物、非终态回归行为不变（既有用例回归保障）。

## Risks

- **豁免过宽**：若未来出现「分支未合入但 merge-base==head」的形态（不可能——merge-base==head 即 head 是 main 祖先），判据自证安全；测试锚定非豁免路径。
- **终态集合漂移**：新终态状态引入时须同步本豁免集合（本仓已有「新状态引入须排查前端 status 枚举」先例，同源风险）。
- 零写侧改动、零落盘契约变化、零守卫变化——不触碰任何打回路径，fail-open 语义保持。
