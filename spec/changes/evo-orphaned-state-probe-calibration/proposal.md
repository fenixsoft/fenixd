# orphaned-state-probe-calibration

## 背景与痛点

防线四 orphaned_state 无驱动探测（c07475ff，2026-09-15 05:22 合入）上线首日即误报：2026-09-15 09:30:12 spec `evo-run-failure-classification-circuitbreaker` 进入 repair 通道并启动活跃 run `repair-evo-run-failure-classification-circuitbreaker-1789464612-a1`（.fenix/logs/fenixd.log:12370-12376；该 run 73 rounds、median 5.8s，09:46:06 正常成功，:12463），09:45:52 却被判「无活动 run / 无存活子进程 / 无待派发」（.fenix/logs/fenixd.log:12461）。

根因是两条探测同时失明：

- ① run_id 前缀归一表 `_RUN_PREFIXES`（core/admin_monitor.py:280）缺 `repair-`，`_spec_from_run_id`（core/admin_monitor.py:2352-2374）对 `repair-…` 返回 None，活跃的 repair run 文件在 `_has_recent_spec_run`（core/admin_monitor.py:357）中不可见；
- ② 进程存活探测 `_pgrep_live_worktree`（core/admin_monitor.py:335）只匹配 `impl-<spec>-` / `verify-<spec>-`，而 repair 进程工作在 `repair-<spec>-<ts>` worktree（core/worktree_manager.py:3479），同样不可见。

同事件中派发的 Administrator 处置 run（`admin-evo-run-failure-classification-circuitbreaker-1789465552`）以 Exit code 1 失败，且失败原因未留证据：.fenix/logs/fenixd.log:12550 仅有 `claude CLI failed: Exit code: 1 | latency: …`。实测同类 admin 失败 run（.fenix/runs/archive/admin-fix-dashboard-read-path-performance-1789583548.jsonl）的唯一 stderr 事件为 `[claude-code:unrecognized_model] {"model":"deepseek-v4.1-flash",…}`——真因被 error-attribution-denoise（core/agent_runner/runner.py:3006-3022）当噪音过滤，error 文本退化为 `Exit code: 1`。

## 目标

- 修复前缀归一与进程存活探测：`repair-` 前缀参与 run 文件活跃度判定与进程存活探测，杜绝「活跃 repair run 被判定无驱动」类误报（两条探测任一恢复即可避免本次误报；两条都修才覆盖「事件间隙 > 宽限 120s」的残留窗口）。
- admin/处置 run 非零退出补可定位证据：附原始 stderr 尾部、退出码、provider/model 与 run 末带时间戳事件，失败可定位；且不得因此废掉 error-attribution-denoise 的全局降噪语义。
- 校准「三条件」判定语义与告警去重表述，避免同信号生命周期记录被误读为重复告警。

## 非目标

- 不改变 orphaned_state 的三条件判定结构（无活动 run/无存活子进程/无待派发），仅扩大条件 ① ② 的可见范围。
- 不改变 15 分钟短阈值与 stuck 阈值（由 `agents.run_timeout_seconds` 单源派生，core/config.py:980-1010；2026-09-16 告警文本实测为 260 分钟）的既有语义。
- 不改变 `_denoise_stderr` 对各类 agent 的既有降噪行为：原始 stderr 仅进 admin 处置失败的证据字段，不回填 error 归因文本（见 design 改动设计 4）。
