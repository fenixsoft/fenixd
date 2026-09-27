# ADR-081：provider 瞬断原地退避优先于换链

date: 2026-09-13
status: accepted

## Context

网关瞬断是分钟级瞬态，但 CLI 对 400 形态错误不重试（白名单仅 5xx/429/断连/流停滞）——runner 层是唯一能补退避的位置。瞬断被 switch 分类直接推进 provider 链的后果：全局瞬断时链上全部 provider 被先后烧尽并冷却（chain_exhausted），dispatch 侧死亡豁免回退预算 + 重试计数清零又拖入无刹车全新重派（新 run_id/新 worktree 从零跑）。跨 provider resume 被 `CLAUDE_CONFIG_DIR` 隔离硬约束阻断（session 不随 provider 迁移），换链即弃现场。

## Decision

- 瞬断优先「等它恢复」：原地退避放 attempt 循环内作子重试（独立计数器，预算=退避序列长度），重跑同一 attempt——provider 不变、run_id 加 `r{n}` 后缀（独立 jsonl，不混流破坏 append-only 契约）、session 续 `--resume`、不触发 switch 冷却不改 chain_cursor；预算耗尽才走现行 switch 冷却 + 链前进。
- 瞬断判定与降噪解耦：判定只看原始结构化信号（全量 stderr_lines 的 switch 类模式匹配，或 exit≠0 + 无 result + stderr 存在 `[claude-code:` 诊断行）；error 文本降噪（过滤诊断行）只影响呈现，任何归因判定不得读降噪后字符串反推；jsonl 原始行不动，取证现场完整。
- worktree 现场全 agent_type 在 attempt 间保留；transient 终态失败走 `keep_for_reuse` 供下轮认领（非 transient 终态失败仍清理，防真实缺陷现场被误续用）；长期无人认领由既有 stale 清扫兜底。
- dispatch 识别 `[provider-transient]` 标记不走死亡豁免重派路径，改排程等待（缺省 600s）后重入队；死亡豁免本身不动（防预算误耗与重派刹车职责正交）。
- 全局错误指纹熔断：错误文本归一化（剥 model 名/时间戳）为指纹，窗口内同指纹超阈值触发全局派发闸门 + major 告警（带节流）；计数与熔断状态进程内存，与既有 4xx 熔断/switch 冷却同构，重启清零可接受。

## Consequences

- 「换链烧全链」与「无刹车重派」两个浪费面关闭；瞬断误报的代价 = 多等一轮退避，可控。
- 原地重试拉长单 run 存活时长：子重试发生在 attempt 循环内（无 claude 进程在跑），进程级 supervision 只盯进程，交互受控；`transient_retry` 事件留痕供排查。
- 退避序列/排程等待/熔断三组旋钮进配置，与 Settings UI 同步落地。
