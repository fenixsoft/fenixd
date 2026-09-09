# Design: fix-frozen-scenario-orphan-reservoir

## Context

2026-09-08 add-verify-contract-autodraft 三连发事故调查（详见对话与记忆 fenixd-frozen-scenario-replay-orphan-reservoir）定位三层缺口：

1. **补齐路径自产孤儿**：`core/pm_engine/verification.py:740-745` 无理由缺场景补齐时，备份缺定义则写 `{"id","description"}` 最小占位——结构性非法（无 kind/steps），写完即被读端 `load_scenarios` 判失败（design D2「补齐不中断验证」反噬）。
2. **持久化集是感染储库**：`diff_planner_output`（`core/verify_scenarios.py:368-372`）以 planner 本轮产出刷新既有条目 kind（planner 丢场景 → kind=None），`save_scenario_set` 写端零校验。admin 只清 test_scenarios.json 未清 scenarios.json，孤儿跨轮复活（现存 scenarios.json 仍残留 7 条）。
3. **重跑无消费硬门**：replan 只内联错误清单进 REPLAN_FEEDBACK.md；「一字不差」检测（verification.py:1171）只记 ERROR 后 hold implemented，recovery 再重派，重复成本全付且外溢 admin/人工往返。

现状读端唯一校验点 `load_scenarios`（`core/verify_engine/scenarios.py:601`）严格校验 kind/steps/navigate；写端四个入口零校验。admin 处置通道已有 `_escalate_env_blocked`（blocked → 自动 admin → 连续 2 轮 frozen → 人工）骨架与 AdminMonitor 15 分钟中断升级机制。

约束：冻结语义（场景集跨轮一致、变更须裁决）不变；admin 修复职权不变；`.fenix/verify-progress/` 属运行时文件不入库。

## Goals / Non-Goals

**Goals**
- 场景三文件全部写入端过同源结构校验，非法条目无法落盘。
- 补齐占位改弃场景，框架不再自产必败数据。
- 持久化集加载净化，斩断储库复活。
- 重跑消费硬门 + 分级升级（admin 代劳，人工只裁决烧钱重出题）。
- 清理现存 7 条孤儿残留。

**Non-Goals**
- 不改冻结「跨轮一致」语义与 admin 裁决边界（重新出题仍须人工批准）。
- 不改 AdminMonitor 15 分钟中断升级机制（本轮事故的人工升级全是 daemon 重启连带，另有治理路径）。
- 不动 planner 出题 prompt 质量治理（出题能力本身，另案）。
- 不做读端 `load_scenarios` 校验规则变更（kind/steps/navigate 规则保持）。

## Decisions

**D1 校验函数单一来源：从 `load_scenarios` 提取纯结构检查函数。**
在 `core/verify_engine/scenarios.py` 新增 `validate_scenario_dicts(raw: list) -> list[str]`（输入 dict 列表、返回错误清单），`load_scenarios` 内部改为调用它（行为零变化），四个写端全部调用它做前置校验。备选：各写端各自 import `TestScenario.from_dict` + `validate()`——重复组装逻辑且易漂移，弃。
*落点：收编写回/补齐写回（verification.py `_apply_scenario_freeze`）、`save_scenario_set`（verify_scenarios.py）、`_scenarios_full.json` 备份更新（verification.py:703-711）。*

**D2 校验失败的写入策略：剔除坏条目继续 + 留痕，非整批拒绝。**
写端遇非法条目时剔除该条目（WARNING/ERROR 留痕 id 清单），合法部分照常落盘。备选：整批拒绝写入——会把单条坏数据放大成整轮验证无法进行，且冻结文件缺失会触发 corrupt 升级，代价过高，弃。特例：补齐写回的坏条目本就来自「备份缺定义」，按 D3 语义剔除。
*三文件一致性：`_scenarios_full.json` 备份仅当全部合法时更新（备份价值在「可恢复」，存毒即失去价值），其余文件剔除坏条目后写入。*

**D3 补齐缺定义 → 登记剔除。**
`_apply_scenario_freeze` 补齐路径备份缺定义的条目：加入「定义不可恢复剔除清单」（新 DiffResult 字段或复用 change_lines），从写回集剔除，验证以剩余场景继续。备选：直接升级 admin 要定义——无理由缺失已是少数路径，缺定义更罕见，为罕见路径加一次升级往返不划算，弃。

**D4 加载净化只动内存、不动文件。**
`load_scenario_set` 读入时剔除无 kind 条目 + WARNING 留痕，不改写 scenarios.json 文件（避免「读操作带写副作用」违反最小意外；文件层面的储库清除由 D5 与清理任务负责）。持久化集条目 kind=None 无法路由 Runner，剔除不损失可执行性。

**D5 消费硬门挂在验收失败比对点，动作改分级升级。**
现有 `prev_replan_error` 比对（verification.py:1170-1215）升级语义：
- 错误清单与上轮相同或为上轮超集 → 判「未消费反馈」，**不再 continue 重跑**，直接走 `_escalate_env_blocked`（title=场景计划争议），admin 唤起。
- 错误实质性消除（数量减少或主体变化）→ 预算内照常重跑。
- 冻结复用路径 corrupt 升级维持现状（已符合第一级语义）。
- `_escalate_env_blocked` 连续 2 轮冻结转人工的既有阈值不动；升级人工的告警描述追加**上轮 planner run 成本**（从 STATE `_cost_usd`/`_tokens_in` 与 run 记录取最近一次 planner run），处置选项文本标注重出题成本。

**D6 admin 修复约束写进处置 prompt + 结果校验。**
admin 唤起 prompt（`prompt_builder.py` 处置指令段）追加：①修复写回必须通过结构校验（写端门自动拦截并反馈）；②`test_scenarios.json` 与 `scenarios.json` 同源坏条目必须同步清理，处置结果须报告两文件状态。校验失败的 admin 写入由 D1 门拦截，admin 收到拒绝反馈后重修（admin run 内自迭代，不额外派发）。

**D7 存量清理为一次性运维操作。**
注册生效后由 admin 或人工清一次 `.fenix/verify-progress/add-verify-contract-autodraft/scenarios.json` 的 7 条孤儿（spec 已 pushed，净化后无实际影响，防未来重验复发）。属运行时操作，列为 tasks 尾项，不计交付物。

## Risks / Trade-offs

- [写端剔除可能掩盖 planner 大面积产出劣化（坏条目被剔、验证照跑）] → 剔除留痕进验证报告场景集变更小节 + 场景数骤降（剔除 >20% 时 ERROR 升级）可见性兜底。
- [消费硬门可能把「网关瞬时故障型坏产物」误判为未消费] → 与「一字不差」同源比对，超集判定要求错误清单结构相同；瞬时故障通常表现为产物缺失/解析失败，走既有 planner 失败分支不进此门。
- [admin 修复被 schema 门反复拒绝形成处置循环] → 门拒绝信息含逐条错误清单，admin 单 run 内自迭代；AdminMonitor 15 分钟中断升级兜底。
- [加载净化改变持久化集条目数，下游 diff 基线变化] → 净化只剔除本就无法执行的条目，diff 侧以净化后集合为基线反而消除了「无理由缺失」假阳性（孤儿条目不再被判定为缺失）。

## Migration Plan

1. 合并后重启 daemon（既有约定：合并后必须重启）。
2. 执行 D7 一次性清理（admin 或人工）。
3. 观察下一轮真实验证的写端拦截与净化日志，确认无误杀。

回滚：revert 提交 + 重启 daemon；写端门为纯前置校验，无数据迁移，无回滚残留。
