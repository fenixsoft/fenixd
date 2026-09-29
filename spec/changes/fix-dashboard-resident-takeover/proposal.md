## Why

2026-09-29 事故实证：agent 自测实例启动时，`serve()` 端口接管逻辑识别占用者为旧 `--serve` 实例后**无差别 SIGTERM 杀掉**，tmux 承载的人工常驻 dashboard 由此被杀、tmux 会话消失；接管者自身装配 `CLAUDE_PID` watchdog + `PR_SET_PDEATHSIG` 双重自杀机制，run 结束即自杀——用户可访问的 8787 实例随机静默死亡，且每次 agent 自测都会复发。

## What Changes

- `serve()` 端口接管路径增加**常驻豁免**：占用者为 dashboard `--serve` 实例、且该进程父进程为 tmux server（复用 `_is_tmux_hosted` 判据，对占用者 pid 的父进程做同源判定）时，MUST NOT 发送任何信号，改为打印可操作错误（含占用者 PID、tmux 常驻说明、`--port` 换端口指引）后非 0 退出
- 非 tmux 承载的旧 `--serve` 实例（agent 临时自测实例、nohup 遗留实例）接管语义不变：仍 SIGTERM 接管
- 错误信息对 agent 可操作：明确提示「用 `--port` 指定其它端口，或直接复用常驻实例」（agent 有自适应能力，会自行换端口）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-instance-lifecycle`: 「端口独占与启动语义」Requirement 增加接管豁免分支——tmux 承载的常驻实例不可被接管；新增对应 Scenario（接管常驻实例被拒绝、接管非 tmux 旧实例仍放行、身份复核窗口内占用者父进程判定）

## Impact

- `core/dashboard/server.py`：`serve()` 接管分支（约 473-493 行）加常驻判定；新增/复用「对任意 pid 判定其父进程是否 tmux server」的辅助函数（`_is_tmux_hosted` 已支持传 ppid，需补「读占用者 /proc/<pid>/stat 取 ppid」一小步）
- `core/dashboard/server.py` 单测：接管路径三形态（tmux 常驻拒绝 / 非 tmux 旧实例放行 / 非 dashboard 占用者报错）的用例扩充
- 无 API/配置/数据迁移；tmux 常驻实例行为不变，agent 自测实例在 8787 被常驻占用时启动失败（预期行为，错误信息指引换端口）
