# ADR-094：裁决产物 fail-closed：不可读 ≠ verified

date: 2026-09-15
status: accepted

## Context

judge 判 bug-found 后，结果文件写 worktree 相对路径、硬门只查主树路径验到上一轮旧合法文件放行、拷回晚于门检且不验新鲜度，非法 JSON 拷回主树后读侧解析失败返回 None，被旧注释按「视为 verified」的 fail-open 语义兜底——judge 的 bug-found 判定 14 秒内走完 verified → done → auto-push。fail-open 不是理论风险，是复发 6+ 次的既有伤口，且语义被两处注释 load-bearing 地引用。

## Decision

- 拷回前置：worktree 产物拷回移到硬门检查之前（成功路径内 `_run_claude` 返回后立即执行），门检继续只查主树路径。不做「门检同时探测 worktree 路径」——两个事实源必然漂移（事故正是主树/工作树双落点分叉所致）；拷回幂等，前置无副作用。
- 硬门验的就是本轮产出：产物新鲜度用 mtime 下界（≥ attempt 启动时刻），不引内容指纹 / 会话 id 绑定——成本高且 judge 无稳定 run 级标识可写入文件；mtime 秒级粒度远大于门检毫秒级窗口，足够。
- 裁决状态白名单单一来源常量，runner 硬门与读侧共用，禁内联副本；读侧返回结构化三态（ok(status) / unreadable(reason, detail)），缺失文件与解析失败不再合并为 None——处置相同（fail-closed），仅告警 reason 区分。
- fail-closed 出口确定：三阶段 = 复用既有裁决重试形态重试一次 → 仍不可读则 blocked + critical 告警（与证据违规分支同构，无新机制）；legacy 降级通道不可读直接 blocked 不重试（结构性异常，自动重派整轮 verifier 只烧钱）。重试轮受在飞状态判据约束（非 testing 丢弃）。
- 语义反转清账：全库 grep 旧 fail-open 措辞（「视为 verified」「按 verified 兜底」「treating as verified」）同步改述 fail-closed 处置——否则下一个改代码的人会按旧注释把语义修回去。prompt 契约同步加固「结果文件必须为合法 JSON、以 json.dump 生成而非手工拼接」。

## Consequences

- 任何路径下不可读裁决（缺失 / 非法 JSON / 白名单外 status）都不得等价于 verified。
- 全绿快道写回失败从静默放行变 fail-closed：宁可 blocked 也不可伪 verified，影响面是罕见组合。
- 三阶段多一轮 judge 重试仅不可读场景触发；硬门白名单 / 新鲜度前置拦截后到达读侧的不可读更少。
