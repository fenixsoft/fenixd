# 代码审查问题台账（items.jsonl）

<!-- knowledge: capability=code-review-items rev=3
     sources=spec/archive/2026-09-24-add-code-review-agent-and-quality-tab,spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume,spec/archive/2026-10-30-evo-add-review-night-defer-snapshot-writeoff -->

代码审查发现跨轮持久化的唯一台账：以 JSONL 逐条记录问题、按指纹去重、按全仓快照核销，向修复 SPEC 生成与 code-fix 车道供料。

## 规则

- 台账路径 `.fenix/code-review/items.jsonl`，每行一条 JSON。
- 每条至少含字段：`item_id`、`project`、`review_id`、`review_kind`、`reviewed_at`、`spec`、`file`、`line`、`severity`、`category`、`title`、`description`、`suggestion`、`evidence`、`fingerprint`、`status`、`spec_name`、`first_seen_at`、`last_seen_at`。
- `review_kind` 取值 `scheduled`（周期自省）/ `manual_full`（手动全仓）/ `manual_window`（手动本周期）。
- `severity` 取值 `critical | major | minor | info`。
- `status` 取值 `open | in_spec | resolved | ignored`。
- `item_id` 唯一且稳定（同一问题重复观测不变）。
- 指纹去重权威：`fingerprint = sha1(file + category + 归一化 title)[:12]`；`title` 归一化规则稳定可复现（去首尾空白、折叠内部空白、大小写统一），保证同一问题跨轮指纹一致、判为同一条目。
- 同一 fingerprint 再次被观测到时不插入新条目，仅更新既有条目的 `last_seen_at`（并刷新 `severity`/`description` 等可变字段）。
- 全仓快照核销资格：`manual_full` 审查完成后，或 `scheduled` 且全仓收集（`window_start=None`，即 scope=`full` 档周期审查）的 run 成功收尾后，台账中仍 `open` 但本轮未再被观测到的条目置为 `resolved`（记录核销时间），不再出现在默认 open 列表；`manual_window` 与窗口档 `scheduled`（`window_start` 非 None）只增不核销（窗口审查只见窗口内文件，部分覆盖下核销必白洗）；一切 error 收场绝不核销（抢救路径只 upsert 落账，`resolve_snapshot` 不可达）；`in_spec` / `ignored` 条目不被自动核销覆盖。
- 快照核销覆盖完整性门（解锁唯一判定点在 run 收尾段，调度消费侧不重复判定）：核销仅在本轮累计覆盖 ⊇ 完整 manifest 时执行——重派 run（携带 `redispatch_of`）以原 run 完整 manifest 为基准、跨重派链累计判定，普通全仓 run（manual_full 或全仓 scheduled）以本轮 manifest 对本轮产物累计判定；manifest 缺失/损坏/为空或守卫异常一律按未覆盖锁定，锁定时维持抢救红线不核销、等剩余文件补齐后由后续 run 解锁（宁锁勿白洗，见 [repo-review-ratelimit-resume](repo-review-ratelimit-resume.md)）。agent 静默少审（自行切批只审 manifest 子集致覆盖不全）同样被锁定。核销另设 observed 非空门：本轮无可归一指纹（findings 缺 file/title）时拒绝核销，防空集核销误置全部 open 为 resolved。
- pending-writeoff 待核销锚：error 收场抢救落账 `inserted` 或 `updated` > 0 时写锚文件 `.fenix/code-review/writeoff-pending.json`（含 `run_id`、`inserted`/`updated`、时刻；flock 原子写），覆盖写——新事故顶旧锚，只留最近一次待核销现场。锚只承载「有部分覆盖待核销」的观测事实，不参与核销解锁判定（解锁唯一由覆盖完整性守卫把关）；写锚失败只留痕，不改变抢救既有语义。
- 锚清除点：任一 run 收尾执行了全仓快照核销，或覆盖完整成功收尾（核销解锁分支走完）时清除；部分覆盖锁定分支保持锚在位，等剩余文件补齐后由后续收尾清除。清锚失败只留痕，不改变收尾终态。
- 锚存在期间，审查完成日志两处落账文案追加「部分覆盖待核销（run_id=…）」标注：观测走日志，不加告警、不进 dashboard 新页；标注读取异常按无锚处理，不影响完成日志主路径。
- 锚驱动剃余续审：锚存在时，周期审查下一轮按「全量清单 − 抢救已落账覆盖文件」的剩余清单派发（复用 429 限流重派既有 `redispatch_of` 形参传锚 run id，收尾守卫按原 run 及其链产物累计覆盖判解锁——MUST NOT 整轮全量重烧，MUST NOT 另起新形参绕过守卫落普通分支）；剩余清单为空则本轮跳过派发（照写同日防重、锚保持原样，核销解锁仍由收尾守卫判定）；剃余失败回退全量清单派发但仍标注 `redispatch_of`（守卫按原 manifest 判覆盖）。结构化留痕 `reason=writeoff_resume`（含剩余文件数与来源 run id）。
- `ignored` 由用户在 Dashboard 显式标记，标记后不出现在默认问题列表。
- `in_spec` 在条目被用于生成修复 SPEC 时自动置入，并记录 `spec_name`；`resolved` 由全仓快照核销置入。
- 状态流转幂等：重复标记为同一状态不报错、不产生副作用。

## 溯源

- 2026-09-24 add-code-review-agent-and-quality-tab（spec/archive/2026-09-24-add-code-review-agent-and-quality-tab） — 新建问题台账：字段契约与三组枚举、指纹去重权威、manual_full 快照核销语义（scheduled/manual_window 只增不核销）、ignored/in_spec/resolved 流转与幂等。
- 2026-10-06 add-code-review-ratelimit-resume（spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume） — 全仓快照核销加装覆盖完整性门：累计覆盖不完整（含重派链口径）不核销，宁锁勿白洗。
- 2026-10-30 evo-add-review-night-defer-snapshot-writeoff（spec/archive/2026-10-30-evo-add-review-night-defer-snapshot-writeoff） — 核销资格从「仅 manual_full」放宽为「manual_full 或全仓收集的 scheduled（window_start=None）」（窗口档与一切 error 收场绝不核销红线不变）；error 收场抢救落账写 pending-writeoff 待核销锚（覆盖写、核销执行或覆盖完整收尾清锚）；审查完成日志追加部分覆盖待核销标注（观测走日志）。
- 2026-10-30 evo-review-night-window-resume-hardening — 待核销锚驱动剃余续审（剩余清单派发、空剩余跳过派发、剃余失败回退全量但仍标注 redispatch_of）；调度侧跨窗顺延时长估计均值改 max（详见 [code-review-agent](code-review-agent.md)）。
