# ADR-087：autostash 删除判据 = 树级 diff 全同 + sha 钉住

date: 2026-09-14
status: accepted

## Context

merge-back stash pop 冲突的自愈会丢弃 stash 版本，而 drop 是删除性操作，误删独有内容不可逆。冲突真实双方是「分支内容 vs 主树并行会话未提交 WIP」——分支间语义冲突走 merge-tree 预演 → repair 通道，不会到达 stash pop。既有自愈缺三面：通知静默、条目滞留无限期堆积、冲突无预警。

## Decision

- drop 判据 = 树级 diff + sha 钉住：pop 前先 `rev-parse stash@{0}` 钉住 sha（主树锁内栈顶即刚 push 的条目）；自愈后对每个冲突文件跑 `git diff --quiet <sha> HEAD -- <file>`——stash 提交树即 stash 时刻工作区快照，HEAD 已含合并结果，退出码 0 即「stash 版被合并结果完全取代」。判据必须树级 diff 而非文本比较，二进制/模式变更天然覆盖。
- 全部文件树级相同才 drop；drop 前再核对 sha 仍为栈顶（防并发插队），sha 记日志保 gc 前可找回。任一文件不同 → 保留条目，告警附 `git show <sha>:<file>` 找回命令。
- 冲突事件在 admin_alerts 留痕可处置：直发复用 admin_store.append 管道，新信号类型必须进监测白名单否则扫描跳过。
- 重叠预警在 stash 之前、预演闸之后，只读不阻断：脏 tracked 文件清单与分支改动文件求交集，交集非空 WARNING 并入告警 description；无重叠零行为变化。
- 存量 stash 条目不批量清理，靠既有 reclaim 巡检按现状 drain（遵循 autostash 勿批量删约定）。

## Consequences

- 误判兜底 = sha 已记日志，gc 前可找回；删除性操作的判据不依赖文本相似度。
- 冲突事件低频（历史 3 个月 5 次），告警无风暴风险，不加节流。
- 冲突信息结构新增字段走属性附加，保持既有元组解包兼容。
