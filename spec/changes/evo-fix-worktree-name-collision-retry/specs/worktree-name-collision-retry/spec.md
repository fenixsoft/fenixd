# worktree-name-collision-retry 规格

## ADDED Requirements

### Requirement: 重名换名重试

worktree add -b 失败且 stderr 含 already exists 时，系统 SHALL 在同一 create 调用内以单调递增时间戳同时重建分支名与 worktree 路径并重试（有界 2-3 次）；分支名末段 SHALL 保持纯数字时间戳，解析契约不变。

### Requirement: 失败语义保持

换名重试耗尽仍失败时，系统 SHALL 沿用现状失败语义（释放本车道创建锁、返回 None），由 runner 层既有 attempt 循环兜底；重试全程 SHALL 持有创建锁不释放。

### Requirement: 换名可观测

每次换名重试 SHALL 落一条含新旧分支名的 WARNING 日志，便于事后对账撞名频率。

#### Scenario: 跨车道同秒撞名自愈

- WHEN 同 spec 的 planner-plan 与 implementer 同秒 create、后到者 worktree add -b 返回 already exists
- THEN 后到者就地换名（时间戳单调 +1）重试成功，两车道各得唯一分支，不消耗 attempt 配额、不触发 sleep 5 秒

#### Scenario: 重试耗尽回退现状

- WHEN 换名重试 2-3 次仍失败（非重名原因或持续冲突）
- THEN 释放创建锁、返回 None，runner 层 attempt 循环按现状兜底

#### Scenario: 分支名解析契约不变

- WHEN 任意 create 返回（或重试后返回）分支名
- THEN 末段为纯数字，queries 层 _spec_from_branch 等解析点行为不变
