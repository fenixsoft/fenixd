# 代码审查问题台账（items.jsonl）

<!-- knowledge: capability=code-review-items rev=2
     sources=spec/archive/2026-09-24-add-code-review-agent-and-quality-tab,spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume -->

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
- 全仓快照核销：一次 `manual_full` 审查完成后，台账中仍 `open` 但本轮未再被观测到的条目置为 `resolved`（记录核销时间），不再出现在默认 open 列表；`scheduled` / `manual_window` 只增不核销（窗口外问题不在本轮观测范围，不得据此判 resolved）；`in_spec` / `ignored` 条目不被自动核销覆盖。
- 快照核销覆盖完整性门：核销仅在本轮累计覆盖 ⊇ 完整 manifest 时执行——重派 run（携带 `redispatch_of`）以原 run 完整 manifest 为基准、跨重派链累计判定，普通 `manual_full` run 以本轮 manifest 对本轮产物累计判定；manifest 缺失/损坏/为空或守卫异常一律按未覆盖锁定，锁定时维持抢救红线不核销、等剩余文件重派补齐后由后续 run 解锁（宁锁勿白洗，见 [repo-review-ratelimit-resume](repo-review-ratelimit-resume.md)）。
- `ignored` 由用户在 Dashboard 显式标记，标记后不出现在默认问题列表。
- `in_spec` 在条目被用于生成修复 SPEC 时自动置入，并记录 `spec_name`；`resolved` 由全仓快照核销置入。
- 状态流转幂等：重复标记为同一状态不报错、不产生副作用。

## 溯源

- 2026-09-24 add-code-review-agent-and-quality-tab（spec/archive/2026-09-24-add-code-review-agent-and-quality-tab） — 新建问题台账：字段契约与三组枚举、指纹去重权威、manual_full 快照核销语义（scheduled/manual_window 只增不核销）、ignored/in_spec/resolved 流转与幂等。
- 2026-10-06 add-code-review-ratelimit-resume（spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume） — 全仓快照核销加装覆盖完整性门：累计覆盖不完整（含重派链口径）不核销，宁锁勿白洗。
