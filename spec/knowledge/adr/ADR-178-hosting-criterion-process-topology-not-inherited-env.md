# ADR-178：进程托管形态判据读进程拓扑——环境变量是可继承污染的弱信号

date: 2026-09-28
status: accepted

## Context

dashboard 孤儿防护第二防线以「自身环境含 CLAUDE_PID ⇒ 本实例是 agent 临时自测实例」为前提绑定 Claude 会话生命周期。tmux server 启动时把启动 shell 的完整环境复制进 pane，人工 tmux 常驻实例同样带 CLAUDE_PID；2026-09-22 实测用户会话 fork 换 PID 后，常驻 dashboard 在 ≤5s 内判死自杀（8787 停止服务）。此前仅一条启动路径以 `env -u` 规避，判据本身未修。反向污染同样存在：daemon 由 tmux 下 supervisor 启动，其子进程 env 经 `os.environ.copy()` 不清洗，agent 起的临时实例也带 TMUX——按「环境含 TMUX」判常驻会把临时自测误判为常驻、漏掉防泄漏。

## Decision

- 实例托管形态判据必须读进程拓扑：父进程身份（/proc/<ppid>/comm 恰等匹配，comm 不可读才回退 cmdline argv0 basename 恰等/前缀判定，禁子串匹配防包装脚本假阳性）。父进程身份不随环境变量继承传播，是干净信号。
- 判据包装为可独立测试的纯函数（入参 pid 可注入），不在守卫函数内联 IO。
- 读取失败（/proc 不可用、非 Linux）回退「按非长驻处理」——fail-safe 偏向防泄漏方向，与既有守卫在异常路径的取向一致。
- 判据落代码是根本修复；各入口命令统一加环境剔除前缀只是双保险——防「记得加前缀」防不住未来新入口。

## Consequences

- 非常规启动形态（父进程为 shell 的嵌套/间接 tmux）退化为修复前行为，不会更糟；tmux 常驻实例自身崩溃无人拉起属人工运维语义，不在防护范围内。
