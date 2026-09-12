## ADDED Requirements

### Requirement: supervisor 目标项目根解析与守卫

`bin/fenixd_supervisor.py` MUST 按「`--project-root` 参数 > `FENIX_PROJECT_ROOT` 环境变量 > `Path.cwd()`」的优先级解析目标项目根，且 MUST NOT 由 `Path(__file__).resolve()` 派生（该路径会跟随项目内 `.fenix/bin` 软链回到框架主树，导致子项目的 supervisor 绑定错误目标）。解析出的项目根下 MUST 存在 `.fenix/`（目录或软链）；缺失时 MUST 打印可读错误并以非零码退出，且 MUST NOT 启动任何 daemon 进程。解析结果 MUST 以绝对路径规范化后作为进程自身的 `${PROJECT_ROOT}` 使用。

#### Scenario: 显式参数优先于 cwd

- **WHEN** 在 `/root/fenixd` 下执行 `python3 .fenix/bin/fenixd_supervisor.py --project-root /root/fenix-server`
- **THEN** supervisor 以 `/root/fenix-server` 为项目根运行，其监视的 restart_request、写入的 daemon_started/supervisor_runtime.json 全部落在 `/root/fenix-server/.fenix/` 下

#### Scenario: 子项目 cwd 兜底不再被软链劫持（事故回归）

- **WHEN** 在 `/root/fenix-server` 下执行 `python3 .fenix/bin/fenixd_supervisor.py`（该项目 `.fenix/bin -> /root/fenixd/bin`），且未设置 `FENIX_PROJECT_ROOT`
- **THEN** supervisor 的项目根为 `/root/fenix-server`，其拉起的是 `/root/fenix-server/.fenix/fenixd.py`，MUST NOT 触碰 `/root/fenixd` 的 daemon、daemon_started 或 restart_request

#### Scenario: 无效目录拒绝启动

- **WHEN** 在不存在 `.fenix/` 的目录（如 `/tmp`）执行 supervisor，且未指定 `--project-root`
- **THEN** 进程打印可读错误并以非零码退出，不产生任何 daemon 进程，也不写入任何 supervisor_runtime.json

### Requirement: supervisor 运行时自报扩展

supervisor MUST 在每次启动时原子覆写 `.fenix/supervisor_runtime.json`（临时文件 + rename），除既有 `sigkill_wait`、`started_at` 外 MUST 追加 `pid`（supervisor 进程 pid）与 `script_hash`（`bin/fenixd_supervisor.py` 内容的 sha256）与 `project_root`（解析出的绝对项目根）。写入 MUST NOT 因失败而中断 supervisor 主流程。

#### Scenario: 自报字段完备

- **WHEN** supervisor 启动完成
- **THEN** `.fenix/supervisor_runtime.json` 同时含 `sigkill_wait`、`started_at`、`pid`、`script_hash`、`project_root` 五个键，且 `pid` 等于 supervisor 自身 pid、`project_root` 等于解析出的项目根

#### Scenario: 写入原子性

- **WHEN** supervisor 正在覆写 supervisor_runtime.json
- **THEN** 任何时刻读取该文件都只能读到完整的旧内容或完整的新内容，不存在半截 JSON

### Requirement: 托管态判定

`core/fenix_session.py` MUST 提供 `supervisor_running(root)`：判定该项目根是否有活跃 supervisor 进程（扫描 `/proc`，`cmdline` 含 `fenixd_supervisor`，且其 `cwd` 或 `--project-root` 参数解析后等于该项目根；`/proc` 不可读时 MUST 返回 False 而不抛异常）。`core/fenix_session.py` MUST 另提供 `hosting_state(root)`，返回 `"managed"`（supervisor 在跑）/ `"unmanaged"`（有 daemon 进程但无 supervisor）/ `"stopped"`（两者皆无）三态之一。

#### Scenario: 托管运行判定为 managed

- **WHEN** 项目同时存在活跃 daemon 进程与活跃 supervisor 进程
- **THEN** `hosting_state(root)` 返回 `"managed"`

#### Scenario: 裸 daemon 判定为 unmanaged（事故回归）

- **WHEN** 项目有活跃 daemon 进程（cwd=项目根，cmdline 含 `.fenix/fenixd.py`），但无任何 supervisor 进程
- **THEN** `hosting_state(root)` 返回 `"unmanaged"`

#### Scenario: 全无判定为 stopped

- **WHEN** 项目既无 daemon 进程也无 supervisor 进程
- **THEN** `hosting_state(root)` 返回 `"stopped"`

### Requirement: 唯一托管启动路径

`core/fenix_session.py:start_daemon(root)` MUST 以 supervisor 托管方式启动：在项目唯一 tmux session（`fenix_session.session_name(root)`）内执行 `cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`，MUST NOT 再以 `python3 .fenix/fenixd.py` 直接作为 session 命令。tmux 在此仅作为脱离终端的承载手段，daemon MUST 是 supervisor 的子进程。启动前 MUST 校验项目根存在 `.fenix` 与 `.fenix/STATE.md`，缺失时 MUST 返回可读错误且不产生任何进程。启动操作 MUST 幂等：`is_running(root)` 为真时 MUST 直接返回 `already=True`。

#### Scenario: 启动后 daemon 的父进程是 supervisor

- **WHEN** 某未运行项目调用 `start_daemon(root)`
- **THEN** 项目唯一 session 内出现 supervisor 进程，daemon 进程的 ppid 等于该 supervisor 的 pid，且 `hosting_state(root)` 返回 `"managed"`

#### Scenario: 重复启动不重复拉起

- **WHEN** 项目 daemon 已在运行，再次调用 `start_daemon(root)`
- **THEN** 返回 `{"ok": True, "already": True}`，不创建第二个 session，项目仍只有一个 daemon 与一个 supervisor

#### Scenario: 非有效项目启动报错不产生进程

- **WHEN** 项目根缺少 `.fenix` 或 `.fenix/STATE.md`
- **THEN** 返回 `{"ok": False, "error": <可读信息>}`，不产生任何 daemon/supervisor 进程

### Requirement: 托管停止语义

`core/fenix_session.py:stop_daemon(root)` MUST 按序执行：① 写 `.fenix/stop`（使 supervisor 不在 daemon 退出后重新拉起）；② 向该项目的 daemon 进程发送 SIGTERM（经 `/proc` 定位，仅限 cwd 或 `--project-root` 等于该项目根的进程）；③ 轮询等待 daemon 与 supervisor 双双退出，上限约 30 秒（daemon 在无 `restart_request` 在册时走既有快速停机语义，supervisor 见 `.fenix/stop` 后自行退出）；④ 超时 MUST 以 `tmux kill-session -t <session>` 强制终止，并对仍存活的 daemon/supervisor 进程补发 SIGKILL；⑤ 无论成败 MUST 清除 `.fenix/stop`。停止操作 MUST 幂等：`is_running(root)` 为假时 MUST 直接返回成功。

#### Scenario: 优雅收口停止

- **WHEN** 某 `managed` 项目调用 `stop_daemon(root)`
- **THEN** `.fenix/stop` 被写入后 daemon 收到 SIGTERM 优雅退出，supervisor 随后自行退出，返回 `{"ok": True, "was_running": True}`，结束后 `.fenix/stop` 不存在且 `hosting_state(root)` 为 `"stopped"`

#### Scenario: 收口超时强制终止不残留孤儿

- **WHEN** daemon 在 30 秒内未退出
- **THEN** 服务端 kill session 并对残留 daemon/supervisor 进程补发 SIGKILL，结束后两者均不存在，返回 `{"ok": True}`

#### Scenario: 停止未运行项目幂等

- **WHEN** 项目无 daemon 与 supervisor 进程，调用 `stop_daemon(root)`
- **THEN** 返回 `{"ok": True, "was_running": False}`，不产生错误，不写入 `.fenix/stop`

### Requirement: 无 supervisor 检测与告警

daemon 启动自检 MUST 把「supervisor 存在性」作为独立判定项，且该判定 MUST NOT 受 `admin.shutdown_drain_seconds` 取值影响（`drain_seconds <= 0` 时仍 MUST 执行存在性检查，仅跳过 drain 一致性比对）。判定为不存在时 MUST 在 `fenixd.log` 落 WARNING，并 MUST 经 AdminStore 写入一条 `severity: major` 的 escalation 告警（`signal_type: supervisor_missing`），描述 MUST 说明「该项目 daemon 未受 supervisor 托管，restart_request 不会被消费」，`recommended_action` MUST 指引经 Dashboard 项目页或 `/fenix-setup` 安装托管。同一未处置告警 MUST 去重，不重复堆积。

#### Scenario: drain=0 项目仍检出无 supervisor（事故回归）

- **WHEN** 项目 `admin.shutdown_drain_seconds` 为 `0` 且无 supervisor 进程，daemon 启动
- **THEN** 日志出现「未受 supervisor 托管」WARNING，且 `admin_alerts.json` 新增一条 `signal_type: supervisor_missing` 的 major 告警

#### Scenario: 有 supervisor 时静默

- **WHEN** 项目有活跃 supervisor 进程且 `supervisor_runtime.json` 与 drain 配置一致
- **THEN** 启动自检不产生任何 supervisor 相关 WARNING 或告警

#### Scenario: 未处置告警去重

- **WHEN** 已存在一条未处置的 `supervisor_missing` 告警，daemon 因故再次启动且 supervisor 仍缺失
- **THEN** 不新增第二条同类型未处置告警

### Requirement: restart-daemon hook 的消费方校验

`core/hook_engine.py` 的 `restart-daemon` 动作写 `.fenix/restart_request` 前 MUST 校验该项目存在活跃 supervisor；不存在时 MUST 返回失败（触发既有 `_alert_failure` 告警链），detail MUST 明确说明「本项目无 supervisor，重启请求不会被消费」，MUST NOT 返回成功。存在时 MUST 维持现行行为并返回成功。

#### Scenario: 无 supervisor 时 hook 报失败（事故回归）

- **WHEN** 项目无 supervisor 进程，某 SPEC 触发 `restart-daemon` hook
- **THEN** hook 审计记录 `status: failure`，detail 含「无 supervisor」，并产生一条 hook 失败告警；MUST NOT 出现「supervisor 将执行优雅重启」字样

#### Scenario: 有 supervisor 时 hook 正常

- **WHEN** 项目有活跃 supervisor 进程，触发 `restart-daemon` hook
- **THEN** `.fenix/restart_request` 被写入，hook 审计记录 `status: success`

### Requirement: restart_failed 升级建议按托管态分支

`core/admin_monitor.py` 的 `restart_failed` 升级告警（`.fenix/restart_request` 超时未清除）MUST 先判定该项目托管态再生成 `recommended_action`：托管态为 `unmanaged`/`stopped` 时 MUST 指引经 Dashboard 项目页「安装 supervisor 托管」或 `/fenix-setup` 恢复托管，MUST NOT 出现「手动启动 `.fenix/bin/fenixd_supervisor.py`」这一类会绑定到框架主树的直接命令；托管态为 `managed` 时 MUST 指引检查 supervisor 进程与 daemon 排水状态。

#### Scenario: 无 supervisor 项目的建议文案安全（事故回归）

- **WHEN** 某 `unmanaged` 项目的 restart_request 超过 10 分钟未清除并触发升级
- **THEN** 该告警的 `recommended_action` 不含「启动 `.fenix/bin/fenixd_supervisor.py`」字样，且含经 Dashboard/`/fenix-setup` 安装托管的指引

### Requirement: 安装 supervisor 托管操作

Dashboard 服务端 MUST 提供 `POST /api/projects/<name>/install-hosting`：对 `unmanaged` 项目执行「停止裸 daemon → 经 supervisor 启动」，使其转入 `managed`；对 `managed` 项目 MUST 幂等返回已托管（不重启）；对 `stopped` 项目 MUST 等价于启动。操作 MUST 复用 `stop_daemon`/`start_daemon`，MUST NOT 绕过它们直接操作进程或 tmux。成功时 MUST 广播 SSE `refresh`。

#### Scenario: 裸 daemon 项目安装托管成功（事故回归）

- **WHEN** fenix-server 处于 `unmanaged`，用户在项目页点击「安装托管」
- **THEN** 裸 daemon 被停止，新 daemon 由 supervisor 拉起，接口返回成功，该项目托管态变为 `managed`

#### Scenario: 已托管项目安装托管幂等

- **WHEN** 对 `managed` 项目调用该端点
- **THEN** 返回成功且不重启 daemon，托管态保持 `managed`

#### Scenario: 未监控项目返回 400

- **WHEN** 对不在监控列表的项目名调用该端点
- **THEN** 返回 400 与「项目不存在」错误
