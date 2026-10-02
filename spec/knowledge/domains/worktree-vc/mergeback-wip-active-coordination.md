# 合回 WIP 占用者识别与事件驱动重试

<!-- knowledge: capability=mergeback-wip-active-coordination rev=2
     sources=spec/archive/2026-10-03-add-mergeback-wip-active-coordination -->

修复批合回被主树 WIP 重叠挡住后的主动协调：机械识别占用者（在飞车道或无主陈旧 WIP）、以持有者 run 终态事件驱动秒级重试、无主限期升级人工——替代固定长间隔被动轮询。

## 规则

### 占用者识别

- 合回被 WIP overlap 挡住时，把 overlap 文件集与在飞实现车道（implementer/code-fix run 的 worktree 分支相对主树 HEAD 的改动文件集，三点式 diff）求交：存在命中即在飞持有者（run/spec/分支/命中文件可追溯），零命中即无主陈旧 WIP；结果随台账 owner_* 字段与进度 current 落盘留痕。
- 识别数据源纯机械（worktree 注册表 `git worktree list --porcelain`、在飞 run 列表、分支 diff），MUST NOT 使用 LLM 推导路径名；在飞车道按 run 前缀过滤（impl-/code-fix-，planner/verifier/admin 不参与），code-fix run_id 无 spec 段经固定 spec 名桥接（code-fix-* → code-review-fix）纳入识别。
- 已知盲区随识别证据留痕：识别只覆盖 worktree 分支型在飞车道；持有者直接改主树不入分支的形态（admin/人工会话、主树内构建产物）分支 diff 必零命中，一律按无主走宽限升级（升级仅为告警，误判影响有界），MUST NOT 为覆盖盲区引入主树写探测。

### 事件驱动合回重试

- 持有者为在飞车道时，以该 run 的终态事件作为合回重试的主要唤醒手段（终态事件到达后秒级自动重试，MUST NOT 等到下一个固定轮询周期）；固定间隔轮询降级为兜底（事件丢失防线），且轮询时重算识别（有主↔无主变化随之更新）。
- per-run 终态监听注册在 agent_runner 终态收口：注册时先查该 run 是否已终态（run 文件终态行口径），是则立即触发回调并消费注册项，不留死监听、不依赖后续事件；注册用 base run_id、触发用 attempt 形态（-r1 后缀），内部归一匹配；同 run 同订阅方重复注册覆盖不累积，单回调异常被 fire 侧兜底、不阻断其余回调与 run 收尾。
- 事件驱动的重试 MUST 复用既有单一重试入口（checkpoint 锁段内、already_running 守卫之后）：锁占用时回调让位不重入，MUST NOT 从事件回调线程旁路直调；在飞批期间事件重试按 already_running 早退，由链边界节拍兜底——秒级让位于正确性。
- 既有 precheck 拦截、merge-tree 预演、主树零污染语义不变：事件唤醒的只是「何时重试」，不是「是否重试」。无 overlap 时零开销（零 git 探测、不写任何 owner_* 字段）。

### 无主陈旧 WIP 升级

- 判定为无主时在可配置宽限（`admin.mergeback_wip_orphan_grace_minutes`，缺省 30；配置 0 = 首次识别即升级，非法负值回退 30）内继续事件驱动等待，期间可能变为有主——转有主即清零宽限计时并转注册持有者终态监听。
- 宽限耗尽 MUST 升级 `mergeback_wip_orphan_stuck` major 人工告警（evidence 附 overlap 文件清单与识别证据/盲区注记），按条目去重不重复升级；MUST NOT 无限期静默等待，也 MUST NOT 自动 stash/丢弃/代提交主树改动（批保持「保留待自动合回」语义，主树 status/HEAD 零触碰）。

### 车道边界

- 本能力挂在 code-fix 修复批的延迟合回消费路径（fix-deferred.json 台账，见 [code-fix-wipgate-defer](../code-fix-lane/code-fix-wipgate-defer.md)）；spec 实现车道的 WIP 等待治理走独立载体（STATE.md 等待标志，见 [wip-defer-merge-retry](wip-defer-merge-retry.md)），两车道互不消费对方载体。

## 溯源

- 2026-10-03 2026-10-03-add-mergeback-wip-active-coordination（spec/archive/2026-10-03-add-mergeback-wip-active-coordination） — 新建本页：占用者机械识别（求交 + run 前缀过滤 + code-fix spec 桥接 + 盲区注记留痕）、per-run 终态监听（agent_runner 终态收口注册、已终态立即触发、attempt 归一、重复注册覆盖与回调异常兜底）、持有者事件驱动重试（复用单一重试入口、锁占用让位）、无主宽限升级（`mergeback_wip_orphan_stuck` major、宽限可配置、禁动主树改动）。
