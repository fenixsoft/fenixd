# ADR-089：WIP 检查点锚定框架静默窗口，merge-back 前塌缩

date: 2026-09-15
status: accepted

## Context

排水杀在飞 run、瞬断退避窗口内 daemon 死亡时，implementer 分支零提交，恢复保留机制因「分支零提交」降级清空重建，整轮从零重做。agent 侧自觉提交覆盖不了锚点场景（进程被杀时 agent 不知道要提交）；runner 定时强提交与 agent 写盘竞态（半成品提交），且与 agent 自身 git 操作撞车。

## Decision

- WIP 检查点 = 框架在「worktree 可证明静默」的时刻提交，锚点无条件下生效（纯保全增强、无资源争议，不配置化）：
  - 锚点 A：排水超时后全部 agent 进程死亡确认之后、孤儿清理之前——进程存活时只写 sidecar 元数据，彼时提交有写竞态；
  - 锚点 B：瞬断退避记录写后、sleep 前——守护退避窗口内 daemon 死亡的重派丢失面。
- 提交消息契约 `fenix(wip): checkpoint <anchor> <spec>`，机器可识别前缀供塌缩扫描与人工审计；`git add -A` 天然尊重 gitignore；空变更跳过；git 操作 15s 超时、失败 WARNING 留痕继续收口——尽力而为的保全增强，任何失败不改变现行行为。
- 主树历史零 WIP 污染：成功收口进入 merge-back 前识别分支上全部 `fenix(wip):` 提交，soft reset 至 merge-base 后以塌缩前最终提交消息重建成单提交（soft reset 不触工作区，文件内容逐字节不变）；塌缩幂等，无 wip 提交零动作。
- 备选否决：agent 侧每条目提交（靠自觉 + 需守卫基建，覆盖不了锚点场景）；接受 WIP 入史（污染主树历史与归档可读性）；merge-back 改 squash（改变所有分支语义）。

## Consequences

- 中断时刻分支上必有可恢复提交，恢复保留路径自动接管高价值续做。
- 塌缩改写分支历史但幂等，且仅在 merge-back 尝试前执行，失败不产生半塌缩状态。
- WIP 提交使 attempt 重试起点工作区 clean——实现者 prompt 本就要求基于工作区现状工作，续跑会话对 git 状态无假设。
- 塌缩 choke point 对全部 lane 统一生效（都在 merge-back 前收口），锚点 B 按 worktree 载体有无自然分派。
