## MODIFIED Requirements

### Requirement: dashboard 端口独占与启动语义

`fenix_dashboard.py --serve` 启动时若目标端口已被占用，MUST NOT 静默僵挂：需检测端口占用者。若占用者为旧的 `fenix_dashboard.py --serve` 实例（命令行匹配 `bin/fenix_dashboard.py` 且含 `--serve`）：

- 占用者**非 tmux 承载**（agent 临时自测实例、nohup 遗留实例）：MUST 先终止旧实例再绑定接管端口（既有语义不变）；
- 占用者为 **tmux 承载的常驻实例**（该进程的父进程为 tmux server——`/proc/<占用者ppid>/comm` 恰为 `tmux: server`，comm 可读但不匹配时回退父进程 cmdline 且仅当 `argv[0]` basename 恰为 `tmux` 或以 `tmux:` 开头方命中，判据与 `_is_tmux_hosted` 同源）：MUST NOT 向占用者发送任何信号，MUST 打印含占用者 PID、tmux 常驻说明与「请用 `--port` 指定其它端口，或直接复用常驻实例」指引的错误后非 0 退出。

若占用者为其它进程（非 dashboard 实例），MUST 明确报错退出并提示占用信息（既有语义不变）。同一时刻 MUST 至多一个 dashboard 实例监听生产端口（端口号来自 `--port > dashboard.yaml port > config port > 默认 8787` 的现有解析链）。

任何情况下启动失败的实例 MUST 在 5 秒内退出进程，不得保留「已运行但未监听」的僵尸实例堆积。

claude 生命周期 watchdog（`_start_claude_watchdog`）与父子生命周期绑定（`_bind_parent_lifecycle`）语义不变：tmux 承载实例不装配、agent nohup 实例照常装配。

接管路径的占用者身份复核（starttime 锚定防 PID 复用误杀）语义不变；tmux 常驻判定在身份复核通过之后、发送信号之前执行，判定所读的父进程身份与占用者 pid 同源快照，不引入额外竞态窗口（父进程读取失败时按非 tmux 承载处理，保持既有接管行为——fail-safe 偏向放行，与 `_is_tmux_hosted` 读取失败返回 False 的既有纪律一致）。

#### Scenario: tmux 常驻实例占用端口时拒绝接管

- **WHEN** 端口 8787 已被 `tmux new-session -d -s fenix-dashboard "... fenix_dashboard.py --serve"` 启动的常驻实例占用（其父进程为 tmux server），此时启动新的 `fenix_dashboard.py --serve`
- **THEN** 新实例 MUST NOT 向占用者发送任何信号（常驻实例继续存活并监听 8787，tmux 会话不消失）；新实例打印包含占用者 PID 与 `--port` 换端口指引的错误后非 0 退出，退出时间 ≤5 秒

#### Scenario: 非 tmux 承载的旧实例占用端口时仍接管

- **WHEN** 端口 8787 已被 agent 经 nohup 拉起的旧 `fenix_dashboard.py --serve` 实例占用（父进程非 tmux server），此时启动新的 `fenix_dashboard.py --serve`
- **THEN** 新实例终止旧实例并成功绑定 8787（既有接管语义不变）

#### Scenario: 占用者父进程判定失败时保持放行

- **WHEN** 占用者为 dashboard `--serve` 实例，但其 `/proc/<ppid>/comm` 与 cmdline 均不可读（父进程已退出等边缘态）
- **THEN** 按非 tmux 承载处理，走既有接管路径（fail-safe 偏向放行，与 `_is_tmux_hosted` 读取失败返回 False 的纪律一致），不产生新的报错分支

#### Scenario: 非 dashboard 进程占用端口时报错退出

- **WHEN** 端口 8787 被无关进程（如 nginx、其它服务）占用
- **THEN** 新实例打印包含占用进程信息的错误后退出，退出前不终止任何进程，状态码非 0（既有行为不变）
