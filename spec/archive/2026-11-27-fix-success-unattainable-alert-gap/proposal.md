# Proposal: fix-success-unattainable-alert-gap

## Why

诚实退出机制的申报面存在静默丢告警缺口：实现 run 以顶层 `status: "success"` 收工但同时在结果文件申报 `unattainable`（fast-track 车道契约下 verified/bug-found 属于 verification.verdict，顶层合同唯一合法值即 success）时，全部既有消费点都以 `partial` 为前提——车道收口不写 `impl_unattainable_tasks` 告警、verified→done 门禁 success 分支不消费申报。2026-11-16 `fix-spawn-attribution-hardening` 事故实证：实现者如实申报 6.3/7.2 不可达成（win-test 通道冻结），SPEC 正常推进到 verified，全程零告警，用户只能靠主动查进度才发现任务缺口滞留。诚实退出的存在意义就是「做不完要如实上报」，该形态让上报静默丢失。

## What Changes

- 车道收口告警消费点归一：fast-track 与 full 车道收口路径消费 `unattainable` 申报不再以 `partial` 为前提——凡结果文件申报了非法外 unattainable（无论顶层 status），收口时统一写 `impl_unattainable_tasks` ESCALATION 告警（severity=warning），人工裁决感知不再依赖用户主动查进度。
- verified→done 门禁 task-gap error 注记申报上下文：未勾任务中存在已申报 unattainable 时，error 文案附「其中 N 项已申报不可达」，fail-closed 语义不变，人工裁决时无需翻结果文件即可感知申报已存在。
- 契约注释澄清：fast-track 顶层合同注释明确 `success + unattainable` 是合法申报形态及其告警语义。
- 判据单点复用：申报解析沿既有 `core.run_task_track` 单源（`parse_unattainable` / `honest_exit_convergence_gap`），不新增第二解析点；非法申报 fail-closed 语义（D2b）不变。

## Capabilities

### Modified Capabilities

- `honest-exit-convergence`：现行规则「partial + unattainable 全覆盖才收敛」不变；新增申报告警面——申报的感知通道（告警 + 门禁注记）从 partial 专属扩展为与顶层 status 无关，堵死 success+unattainable 静默丢申报形态。

## Impact

- 代码面：`core/pm_engine/dispatch/fast_track.py`（车道收口告警前提）、`core/pm_engine/dispatch/queue.py`（full 车道对称点）、`core/pm_engine/engine.py`（task-gap error 注记）、`core/run_task_track.py`（申报解析 helper 复用口）、`core/event_bus.py` 无涉及。
- 行为面：partial 路径行为零变化（既有收敛判据、告警、fail-closed 全保留）；纯 success 且无申报的路径零变化（不引入误报）；仅 success+unattainable 形态从「静默」变「告警 + 注记」。
- 测试面：`tests/test_honest_exit_convergence.py` 等既有诚实退出回归全量保持；新增 success+unattainable 告警与注记场景。
