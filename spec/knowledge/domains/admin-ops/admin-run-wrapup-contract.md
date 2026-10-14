# 管理员 run 收尾契约（封顶收尾宽限与处置记录先行）
<!-- knowledge: capability=admin-run-wrapup-contract rev=1 sources=spec/archive/2026-10-15-evo-add-admin-run-wrapup-contract -->

保障非实现车道 run 不死于收尾半途：扩容封顶点对任务已清零的 run 发一次性收尾宽限落终稿，处置记录先于长恢复动作落盘。

## 规则

### 收尾宽限（框架侧）

- 触发点有两处：轮数扩容封顶点（turn extension 用满处）与墙钟监督扩容次数封顶点（max_extensions 用满处）。两处对同时满足以下条件的 run 发放一次性收尾宽限：agent_type 属收尾宽限车道集合 `WRAPUP_GRACE_AGENT_TYPES`（administrator / dispute-judge / spec-review / self-review / code-review / code-fix / verifier，与实现车道集合 `IMPL_LANE_AGENT_TYPES` 不相交，impl-ocr 属实现族语义有意排除）；run 内自建任务清单全部 completed。
- 宽限量默认 20 轮，配置键 `agents.wrapup_grace.{enabled, turns}`（缺省 true / 20，归一化单点 `get_wrapup_grace_config`，非法值逐项回退缺省），轮数侧与墙钟侧共用同一配置开关键。墙钟侧按「宽限轮数 × 该 run 近期平均每轮墙钟」折算秒数并 clamp 到既定上下限，落 `wrapup_grace_seconds` 供墙钟上限一次性抬升，保证发放的宽限窗口真实可用。
- 一次性发放：已发放标记 `wrapup_grace_granted` 落 `_turn_branch_state[run_id]`，轮数侧与墙钟侧共用同一状态槽，不重复发放。宽限耗尽仍未终态时按既有击杀路径落终态。
- 不触发情形：run 内自建任务仍有未完成项时维持既有流量型续期判据；run 无任何 TaskCreate 记录（自建任务清单为空）时不发放，按既有封顶击杀路径落终态——判据自带收窄，planner / verifier 等极少建任务的车道天然不触发。
- 宽限窗口应用于收尾动作（写最终处置记录、end_turn），不用于开启新实验。
- 判据数据源：run 产物 TaskCreate/TaskUpdate 解析的 run 内自建任务完成态（与 ADR-275 数据源选型同源）；spec tasks.md 的 remaining_tasks 是静态快照口径、对在飞 run 自建任务零对应，不纳入任何车道的续期/宽限判据。
- reason/evidence 纪律：宽限发放与耗尽在轮次续期/监督 evidence 注记 `wrapup_grace`；reason 文案不得改动既有豁免匹配子串（budget 豁免按 reason 子串匹配），观测信息只进 evidence 不进 reason。

### 处置记录先行契约（administrator 提示词硬约束）

- 诊断闭环判定后（根因已定、环境已定版、实验已收敛、修复计划已成稿）MUST 先把最终处置记录覆盖写入处置文件，再执行环境恢复/清理/重启等长动作——初步记录是动手前保险，终稿覆盖写是收尾时保险，任何时刻被杀都不丢结论。
- 自建任务全部 completed 后 MUST NOT 开启新一轮诊断实验（新探针、新实验组、新的深挖分支）；剩余动作只允许写最终处置记录、执行已计划的恢复/清理、结束。
- 最终处置记录不得留作最后一个动作：连续执行恢复/清理/验证类动作而处置文件仍只有初步记录时，立即停下先覆盖写终稿再继续。

## 关键行为

- 轮数侧判定位于 runner.py 轮次上限扩容封顶分支，墙钟侧位于 liveness.py 监督超时扩容封顶分支；实现车道的预算/早停由 sizing 与 kill_early 管辖不变，两车道集合不相交故与 impl 早停、预算 sizing 不互相触发。
- 单元测试基线 tests/test_admin_wrapup_grace.py：末次扩容点触发宽限、宽限耗尽落终态、任务未清零不触发、impl 车道不受影响四类。

## 溯源

- 2026-10-15 evo-add-admin-run-wrapup-contract（spec/archive/2026-10-15-evo-add-admin-run-wrapup-contract） — 新增本页全部规则：轮数/墙钟扩容封顶点一次性收尾宽限（非 impl 车道 + run 内自建任务全 completed，默认 20 轮可配，两侧共用开关键与发放状态）、判据数据源与 reason/evidence 纪律、administrator 处置记录先行三条硬契约
