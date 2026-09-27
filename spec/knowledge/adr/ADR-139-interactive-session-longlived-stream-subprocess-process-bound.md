# ADR-139：交互式自由会话为长驻流式子进程，状态仅存 dashboard 进程内

date: 2026-09-23
status: accepted

## Context

dashboard 需要面向人的项目级交互式会话。候选形态中「每轮 `--continue` 重启进程」每轮重新加载上下文、延迟与 token 成本双高，且丢失「进程还活着」这一最简状态定义；会话若落盘则引入历史/resume 一整套受管状态。dashboard 进程零新增 Python 依赖是既有约束。

## Decision

- 会话 = 一条长期存活的 `claude` 子进程，`-p --input-format stream-json --output-format stream-json --verbose` 流式双向 I/O，每行输入触发一轮、进程不退出；MUST 带 `--replay-user-messages`——无回显时用户输入既对用户不可见、也不进服务端缓冲，重开接回会丢全部用户轮次。
- 会话状态与事件缓冲只活在 dashboard 进程内：有界环形缓冲（超限截断并显式标记，不静默丢历史）、空闲超时回收、随进程退出消失；无落盘、无历史、无 resume、不产生 run 文件、不与 agent_runner 共享会话池。每项目至多一会话，重复打开即接回。
- 安全边界：spawn 的 cwd 锁死为该项目的注册根路径，MUST NOT 接受请求传入的任意 cwd——bypassPermissions 的可达面由此被限定在项目根内。事件过滤只作用于自由会话；run 产物是审计凭据，须保全量不过滤。
- 前端以事件信封 uuid 为内在键去重，重开接回 = 全量重拉缓冲 + uuid 去重，不做服务端游标/断点续传。

## Consequences

- 交互形态简单有界；dashboard 崩溃丢失会话属可接受（会话进程不持独占资源，孤儿空转至 idle 超时回收，读线程 EOF 兜底广播明确终态）。
- 依赖 CLI 流式输入的长期存活语义，MUST 配真实起进程的集成测试钉住该行为，CLI 行为变化即报警。
