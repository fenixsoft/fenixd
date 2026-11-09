# dsh tidy 挂接必须覆盖全部直调车道（maintenance_runs 漏挂教训）

## 背景

`add-dsh-session-title-archive` 3.3 的会话归档挂接（`_dsh_session_tidy_on_terminal`）最初只落在两处：`_execute_agent` finally（dispatch 族：impl/verify/repair/planner/judge）与 dispute-judge/spec-review 直调函数各自的 finally。但 fenixd 还有第三类执行面——`core/agent_runner/maintenance_runs.py` 的直调车道（`run_administrator` / `run_arbiter`），它们不经过上述任何终态外口。

## 结论

任何「终态资源清理/投递」类挂接，落点必须枚举**全部**执行面而非只见 dispatch 族：`_execute_agent` finally、dispute-judge/spec-review finally、maintenance_runs 直调车道主 run try finally。新增直调车道（同 run_administrator 骨架：claim→组装→_run_agent→硬门→指标收尾）时，主 run try 必须自带终态挂接；测试面用「端到端替身跑真函数 + AST 源码契约」（对齐 `test_run_agent_call_site_arity.py` 先例）双保险钉死。维护车道注入的 facade 替身可能缺目标方法，挂接用 `getattr` 判空静默跳过（logger 判空同款先例）。

## 证据

- 2026-11-09 cloud-phone web 未分组 9 条中 6 条系本缺陷：admin ×4（admin-global-1794210416 / admin-m3-…-1794210116 / admin-m3-…-1794214619 / admin-single-app-realdevice-retest-1794215520）+ arbiter ×2（arbiter-p2p-crossnet-traversal-1794215565 / -1794216592）——run jsonl `system/init` 坐实各 spawn 了独立 dsh 会话且 run 已终态，但归档 trail 零命中、`dsh_session_tidy/pending.jsonl` 空。
- 修正：两车道主 run try 补 finally 投递（commit 见 verification-report 修正三）；TDD 3 用例（arbiter 成功/异常端到端 + AST 契约）先红后绿，关联 7 套件 169 passed；6 条存量经生产 helper 手工归档。
- 关联：同日另一挂接缺陷见 `dsh-tidy-attempt-session-registration.md`（多 attempt 注册覆盖）与 `dsh-session-created-append-gate.md`（bundle 侧 append 闸）。
