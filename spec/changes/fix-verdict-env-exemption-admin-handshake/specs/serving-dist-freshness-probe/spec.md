# spec-serving-dist-freshness-probe

## ADDED Requirements

### Requirement: verify run 前 dist 新鲜度探针
验证链在开跑场景前 SHALL 对被测 dashboard 实例的构建产物执行新鲜度探针：比对 dashboard static src 树与本轮 served dist 的时序（src 最新内容时间晚于 dist 构建时间即为滞后）。探针判滞后时 MUST NOT 直接开跑场景——先执行自动重建（与 merge-back `_rebuild_dist_after_merge` 同源的构建方式，从合并后 src 重建 served dist）再开跑。

#### Scenario: dist 滞后先重建再开跑
- **WHEN** merge-back 已合入新 src 文案而 served dist 为中间态构建，本轮验证开跑前探针判定 dist 滞后
- **THEN** 框架自动重建 dist 成功后开跑场景，空态文案等 src 断言打到新鲜产物，不再产生 dist 时序类 env 失败

#### Scenario: dist 新鲜时零开销直通
- **WHEN** served dist 构建时间晚于 src 最新内容时间（无滞后）
- **THEN** 探针直通不执行重建，不产生额外构建耗时与副作用

### Requirement: 重建失败不静默继续
探针判滞后但自动重建失败时，框架 SHALL 显式暴露（run 错误现场 + 日志 error），MUST NOT 以陈旧 dist 静默开跑全批场景——继续开跑的决定 SHALL 与升级路径联动（按环境性失联语义处置），使该轮失败可被后续豁免握手与 admin 升级链消费，而非落地为无法归因的 env warning。

#### Scenario: 重建失败升级而非静默开跑
- **WHEN** 探针判 dist 滞后且 `npm run build` 失败（编译错误等）
- **THEN** 本轮不静默开跑 web 场景，错误现场记录构建失败尾部日志，按环境性失联路径回 implemented 重验/升级，人工可见「重建失败」而非「场景 env warning」
