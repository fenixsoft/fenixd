# Run 产物生命周期与保留策略
<!-- knowledge: capability=run-artifact-retention rev=2
     sources=spec/archive/2026-09-09-remove-auto-run-cleanup,spec/archive/2026-09-21-fix-dashboard-read-path-performance,spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive -->

run 产物的数据生命周期绑定 SPEC 生命周期：SPEC 未归档产物可回看，SPEC 归档产物即清理；无显性 SPEC 的车道产物按天龄兜底清除，生产数据不被任何按容量裁剪的匿名机制删除。

## 规则

- **顶层产物只增不减**：`.fenix/runs/` 顶层的 `*.jsonl` 不得被任何代码按数量、时间或阈值自动删除；文件离开顶层的唯一途径是保留清扫器把终态 run 产物移入 `.fenix/runs/archive/`（活跃目录有界性由「终态即移出」保证）。dashboard 聚合/列表请求（任意次数、任意端口）不得改变顶层文件集合。
- **归档目录无容量上限**：`.fenix/runs/archive/` 中归属活跃 SPEC 的产物在其 SPEC 归档前不被任何路径删除，归档条目数不设上限；禁止以保留 N 条最旧优先之类的方式对归档目录做容量裁剪。
- **产物清理唯一挂靠 SPEC 归档**：SPEC 归档动作（`archive_spec_runs`，唯一入口，CLI 与 `spec_archive.py` 两条归档路径及 dashboard 手工归档路由都收敛到它）把该 SPEC 的 run 产物（`run_spec_part` 与 SPEC 名全等匹配）从**顶层与 archive/ 归档副本两处一并删除**；删除逐文件记日志（可审计），单文件失败记 WARNING 继续其余文件，不阻断归档主流程；不属于该 SPEC 的产物零影响。
- **无主车道产物按天龄兜底**：清扫器删除 archive/ 中 `run_spec_part` 归属不匹配任何活跃 SPEC（`spec/changes/` 下无同名目录）且 mtime 距今超过 14 天（模块常量）的 `*.jsonl`，覆盖 code-fix / admin-global / code-review 等无显性 SPEC 的车道产物；逐文件记日志，单周期删除量有批次上限防 I/O 尖峰。
- **无主判定现算 + fail-closed 防误删**：活跃 SPEC 集每轮清扫实时取 `spec/changes/` 目录名集合，不缓存；扫描失败时跳过本轮兜底清理（仅记 WARNING），不得按空集处理；`spec/archive/` 已归档 SPEC 不计入活跃集——归档 SPEC 未删净的残留产物按无主天龄清理。
- **双保险闭环**：SPEC 归档时未删净的残留产物因无主判定现算而自动落入无主集，由 14 天兜底最终清除；归属活跃 SPEC 的产物不受兜底影响（只受 SPEC 归档清理管辖）。
- **`runs.keep` 配置已取消**：配置体系无 `runs` 键（受管键清单、缺省展示、回显与写入分支均不含）；存量 config.yaml 中已写入的 `runs.keep` 为死键，读取无害、无迁移要求；配置管理接口收到含 `runs` 键的补丁时忽略该键（不落盘、不回显），其余键正常应用。
- **归档产物 SPEC 未归档期间可回读**：spec 详情页时间轴与运行记录的数据源覆盖 archive 目录；消费 run 转录的聚合/对账读取按「顶层 → archive/ 副本」双路径回退。
- **行为边界**：SPEC 归档后其 run 产物（LLM 对话转录）不可再回看，时间轴运行节点随之消失（状态转换节点来自 daemon 日志，不受影响）；终态 SPEC 的耗时/成本汇总已固化进 STATE.md，不受产物清理影响。

## 关键行为

保留清扫器以固定周期执行两步：① 终态 run 产物从顶层移入 `archive/`（活跃目录有界性）；② 遍历 `archive/*.jsonl` 按无主判定做天龄兜底删除。SPEC 归档则触发 `archive_spec_runs` 对该 SPEC 产物的两处清理。三条路径互不替代：①保证顶层有界，归档清理保证 SPEC 证据随生命周期收敛，兜底保证无主产物不无限堆积。

## 溯源

- 史前基线 — runs 产物按保留策略清理，转录与结果文件限期保留，防磁盘无限膨胀。
- 2026-09-09 2026-09-09-remove-auto-run-cleanup（spec/archive/2026-09-09-remove-auto-run-cleanup） — 按数量保留的自动清理基线已随该归档废除；改立「顶层只增不减、归档唯一入口是 SPEC 归档」，并同步删除清理代码与 runs.keep 配置及设置页输入项。
- 2026-09-21 2026-09-21-fix-dashboard-read-path-performance（spec/archive/2026-09-21-fix-dashboard-read-path-performance） — runs.keep 由死键落地为真实归档清理消费点（归档目录按 keep 上限最旧优先删除）；该裁剪机制已随 2026-10-06 归档再度废除。
- 2026-10-06 2026-10-06-fix-run-cleanup-attach-spec-archive（spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive） — 产物清理升级为挂靠 SPEC 归档（顶层与归档副本一并删除）；归档目录取消 keep 上限，runs.keep 配置面整体拆除（含 config_admin 受管键与两处同文件触点）；新增无主车道产物 14 天兜底、无主判定现算与活跃集扫描失败 fail-closed 防御。
