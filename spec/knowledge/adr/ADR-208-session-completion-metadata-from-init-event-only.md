# ADR-208：会话补全元数据以 CLI init 事件缓存为唯一口径——禁自扫 skills/命令目录，init 事件捕获后不进事件缓冲与 SSE

date: 2026-10-03
status: accepted

## Context

会话输入控件的斜杠补全需要「当前会话进程真实可用的斜杠命令与 skill 列表」。两个备选数据源：后端自行扫描 `~/.claude/skills` 与项目 `.claude/skills` 目录推导列表；或读取 claude CLI 会话进程 stdout `type=system, subtype=init` 事件中现成的 `slash_commands`/`skills` 数组。自扫无法对齐插件与内建命令口径（扫描即漂移，且成本常驻）；init 事件是 CLI 官方口径，天然反映该进程真实可用集合。此外 init 事件此前会进入事件缓冲并 SSE 广播，而前端对其零渲染依赖——捕获后丢弃不产生任何可见回归。

## Decision

- 命令/skill 补全元数据的唯一权威源 = SessionManager 从会话进程 stdout init 事件缓存的 `slash_commands`/`skills` 数组；后端与前端 MUST NOT 自行扫描 `~/.claude/skills`、项目 `.claude/skills` 或其它目录推导该列表。
- init 事件被读线程捕获写入 Session 缓存后即丢弃：MUST NOT 进入事件缓冲、MUST NOT 转发给 SSE 订阅者；「前端对 init 零渲染依赖」是本裁定的前提，未来新增 init 消费点必须改为读缓存，MUST NOT 以恢复广播的方式取数。
- 缓存随 Session 生命周期存亡：会话进程终止、Session 被移除后缓存一并不可达（端点返回空数组而非陈旧缓存）；会话重启后以新 init 事件内容覆盖。
- 无在飞会话或 init 未到达时补全静默降级为空候选，不弹错误、不阻塞输入。

## Consequences

- 数据口径零漂移：列表恒等于 CLI 自报的真实可用集合，插件/内建命令无需维护映射表；代价是 init 未到达前补全不可用（实测 CLI 的 init 仅随首条用户消息到达，新会话首条消息发出前为空），属接受的降级路径。
- 「hook_* 丢弃、init 捕获后丢弃、其余保留」成为会话事件流过滤的登记样板；后续新增事件类型必须显式归入三者之一，不得默认透传。
- 后续需要命令/skill 元数据的新能力（命令面板、技能审计等）必须经 SessionManager 缓存读取，不得另立扫描通道。
