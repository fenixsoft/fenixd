<!-- knowledge: capability=timeout-supervision rev=1 sources=spec/archive/2026-09-22-evo-supervision-timeout-config-consistency -->

# 超时监督配置一致性

supervision `absolute_max_seconds` 下限的单一派生口径与启动/热更新一致性校验：显式配置的硬上限不被静默改写。监督的活性评估与续期流程见 [agent-run-timeout-supervision](agent-run-timeout-supervision.md)。

## 现行规则

- absolute_max_seconds 的下限由单一派生函数给出（`supervision_floor`），公式为「生效 run_timeout_seconds + 续期预算 × extension_seconds」；config 校验层与 liveness 兜底层调用同一实现，禁止两处各自手写常数。
- 运行时口径（liveness 兜底）：生效 run_timeout 取 `agents.timeout_overrides.<agent_type>` 或全局 `agents.run_timeout_seconds`；续期预算取 `max_extensions`，fast-track 且 `_fast_track_scale_tier == "higher"` 时 +2（保持 fast-track 加成语义）。
- 配置校验层口径（启动/热更新）：取该部署可达的最大下限 `max(全局 run_timeout_seconds, agents.timeout_overrides 全部值) + (max_extensions + 2) × extension_seconds`，以 +2 保守覆盖 fast-track higher 档；配置层沿用「按最大可达续期预算」的保守口径，不下调。
- 配置加载（启动或热更新）时校验 `absolute_max_seconds ≥ 配置校验层下限`；`timeout_supervision.enabled=false` 或缺段时不校验。
- 不一致时先输出明确 ERROR（含两侧配置值、配置校验层下限与修正建议：抬升 absolute_max 或下调 run_timeout），随后按序处置：默认 `timeout_supervision.auto_align=true` 时自动对齐——absolute_max 抬升至下限，内存生效并持久化（复用受管键白名单 + 原子写的既有配置写路径，不直接写配置文件），该分支不抛异常，启动与热更新均继续；auto_align 被显式关闭且 supervision 启用时 fail-fast 阻断——启动/加载返回失败，热更新拒绝新配置并保留旧值。自动对齐分支先执行，仅当其被显式关闭才进入阻断分支，两者不同时生效。

## 溯源

- [2026-09-22 evo-supervision-timeout-config-consistency](spec/archive/2026-09-22-evo-supervision-timeout-config-consistency/) — 两处手写下限口径收编为单一派生函数；配置校验层改按部署最大下限；不一致处置由「告警+兜底」改为默认自动对齐（可显式关闭转 fail-fast）
