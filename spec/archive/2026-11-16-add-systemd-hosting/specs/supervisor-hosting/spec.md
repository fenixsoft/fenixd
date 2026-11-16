## MODIFIED Requirements

### Requirement: 唯一托管启动路径

`core/fenix_session.py:start_daemon(root)` MUST 以 supervisor 托管方式启动：对目标项目确保存在 `fenixd-<项目名>.service` unit（缺失时生成安装），并 `systemctl enable --now` 启动（unit 的 `ExecStart` 为 `python3 .fenix/bin/fenixd_supervisor.py --project-root <root>`）。MUST NOT 再创建 tmux session，MUST NOT 以 `python3 .fenix/fenixd.py` 直接作为启动命令；daemon MUST 是 supervisor 的子进程。启动前 MUST 校验项目根存在 `.fenix` 与 `.fenix/STATE.md`，缺失时 MUST 返回可读错误且不产生任何进程。`systemctl` 不可用时 MUST 返回可读错误且不产生任何进程（不回退 tmux）。启动操作 MUST 幂等：`is_running(root)` 为真时 MUST 直接返回 `already=True`；unit 已启用且服务活跃时重复调用 MUST NOT 重建或重启服务。

#### Scenario: 启动后 daemon 的父进程是 supervisor

- **WHEN** 某未运行项目调用 `start_daemon(root)`
- **THEN** `fenixd-<项目名>.service` 被安装并启用，supervisor 进程出现，daemon 进程的 ppid 等于该 supervisor 的 pid，且 `hosting_state(root)` 返回 `"managed"`

#### Scenario: 重复启动不重复拉起

- **WHEN** 项目 daemon 已在运行，再次调用 `start_daemon(root)`
- **THEN** 返回 `{"ok": True, "already": True}`，不重建 unit、不重启服务，项目仍只有一个 daemon 与一个 supervisor

#### Scenario: 非有效项目启动报错不产生进程

- **WHEN** 项目根缺少 `.fenix` 或 `.fenix/STATE.md`
- **THEN** 返回 `{"ok": False, "error": <可读信息>}`，不产生任何 daemon/supervisor 进程，也不写 unit

#### Scenario: systemctl 不可用拒绝启动（tmux 回退退役）

- **WHEN** `systemctl` 不可用时调用 `start_daemon(root)`
- **THEN** 返回 `{"ok": False, "error": <含「需要 systemd」指引的可读信息>}`，不产生任何进程，MUST NOT 创建 tmux session

### Requirement: 托管停止语义

`core/fenix_session.py:stop_daemon(root)` MUST 按 unit 接管状态双轨执行：

- **unit 已安装**（systemd 承载）：① 写 `.fenix/stop`；② `systemctl stop --no-block`（MUST NOT 同步等待——systemd 停机链走 supervisor 既有 SIGTERM 转发收尾与排水窗）；③ 轮询等待 daemon 与 supervisor 双双退出，上限约 30 秒（保留既有快速停机契约与 dashboard stop 端点 30 秒预算）；④ 超时对入口快照中仍存活的残留 daemon/supervisor 进程补发 SIGKILL（快照对象为 stop 入口一次经 `/proc` 定位的项目进程集合，MUST NOT 重新扫描——既有并发安全契约保持）；
- **unit 未安装但进程在跑**（managed-but-no-unit 态，含迁移期与人工直启）：保留既有直接信号链——写 `.fenix/stop` → 经 `/proc` 定位向该项目 daemon 发 SIGTERM → 轮询等待（上限约 30 秒）→ 超时对残留 daemon/supervisor 补发 SIGKILL。

两条轨的停止操作均 MUST 幂等：`is_running(root)` 为假时 MUST 直接返回成功；⑤ 无论成败 MUST 清除 `.fenix/stop`。unit 未装且进程在跑时 MUST NOT 因 `systemctl stop` 对未启动 unit 是 no-op 而谎报成功。tmux kill-session 兜底 MUST 退役。

#### Scenario: unit 承载项目优雅收口停止

- **WHEN** unit 已安装且服务活跃的项目调用 `stop_daemon(root)`
- **THEN** `.fenix/stop` 被写入后 `systemctl stop --no-block` 触发 supervisor 既有 SIGTERM 收尾链，daemon 优雅退出，supervisor 随后退出；返回 `{"ok": True, "was_running": True}`，结束后 `.fenix/stop` 不存在且 `hosting_state(root)` 为 `"stopped"`

#### Scenario: 收口超时强制终止不残留孤儿

- **WHEN** unit 承载项目 stop 后 daemon 在 30 秒内未退出（深排水）
- **THEN** 对残留 daemon/supervisor 进程补发 SIGKILL，结束后两者均不存在，返回 `{"ok": True}`

#### Scenario: managed 但无 unit 时走直接信号链

- **WHEN** supervisor/daemon 进程在跑但 unit 未安装，调用 `stop_daemon(root)`
- **THEN** 按既有直接信号链停止（SIGTERM → 等待 → 超时 SIGKILL），返回 `{"ok": True, "was_running": True}` 且进程全无

#### Scenario: 停止未运行项目幂等

- **WHEN** 项目无 daemon 与 supervisor 进程，调用 `stop_daemon(root)`
- **THEN** 返回 `{"ok": True, "was_running": False}`，不产生错误，不写入 `.fenix/stop`
