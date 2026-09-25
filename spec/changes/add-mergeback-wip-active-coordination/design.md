# 设计：add-mergeback-wip-active-coordination

## Context

- 现状（`evo-add-codefix-batch-wip-precheck` 落地的 precheck + `evo-add-wip-defer-merge-retry-consumer` 的 defer 消费者）：合回前 WIP overlap precheck 拦截（policy=escalate，主树零污染），批转 defer 保留待自动合回，由固定间隔轮询被动重试。
- 实测（09-24）：overlap 挡住 → 47min 后才合回成功，期间 14:45 曾重试仍挡；占用者是并行 SPEC 实现车道（改同一批 dashboard 文件）。框架对占用者零感知。
- 主树 WIP 的合法来源是并行实现车道的交付物（在 dashboard 主树 preview 等场景存在），也有历史陈旧 WIP（autostash 事故族）——两类必须区分对待。

## Goals / Non-Goals

**Goals:**
- 挡住时知道「谁占着、还会占多久」（在飞即订阅其收尾；无主即限期升级）
- 在飞持有者收尾 → 秒级重试合回，替代 47min 级被动等待
- precheck 安全语义零放松

**Non-Goals:**
- 不改 overlap 的判定规则与 policy（`escalate`/`block` 语义不变）
- 不做主树 WIP 的自动 stash/丢弃/代提交（autostash 事故族红线）
- 不治理并行车道间的文件级规划（那是调度层课题）

## Decisions

- **D1 识别数据源纯机械**：在飞 run 列表（agent_runner 注册表）× 各 run 分支 `git diff --name-only <主树HEAD>..<分支>` 与 overlap 文件集求交。禁 LLM 推导路径名（code-review 分片名教训）。零命中 → 无主。
- **D2 唤醒机制**：订阅 agent_runner 既有 run 终态事件（defer 批的合回消费者注册对持有者 run_id 的监听）；终态到达 → 立即重试合回。兜底轮询保留（现状间隔），且轮询时若识别结果变化（有主→无主）随之更新。
- **D3 唤醒通道防静默丢失**：`scheduling_kick` 单槽位有 conflict 写入假成功缺陷（fix-scheduling-kick-single-slot-spec 已立项），本 SPEC 不依赖它作为唯一唤醒；事件监听 + 轮询兜底双通道，任一到达即可。
- **D4 无主宽限 30min 后升级**：复用 `mergeback_wip_overlap`（admin major，处置指引已存在），触发点从「挡住即发」后移到「确认无主 + 宽限耗尽」，降噪（在飞持有者场景不再打扰人工）。宽限可配置（缺省 30，对齐 admin cooldown 量级）。
- **D5 defer 批语义兼容**：识别与订阅挂在 defer 消费路径上；defer 批的「保留待自动合回（不烧失败预算）」语义不变，升级告警不改变批的预算/台账状态。

## Risks / Trade-offs

- [在飞 run 改动集巨大导致 diff 求交慢] → diff 限 `--name-only` 且在收到 overlap 通知时一次性计算（非每轮询）；实测 worktree 分支 diff 为亚秒级
- [持有者 run 终态后合回仍挡（它收尾时又留下新 WIP）] → 重试后仍挡则回退 defer 轮询路径，识别随之重算
- [事件监听泄漏（run 已终态后才注册）] → 注册时先查该 run 是否已终态，是则立即触发重试，不依赖后续事件

## Migration Plan

合入即生效；defer 轮询保留为兜底，无行为回退风险。回滚 = revert 消费路径改动。
