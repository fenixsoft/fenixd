# Proposal: fix-run-cleanup-attach-spec-archive

## Why

run 产物清理与 SPEC 生命周期是两套互不感知的机制，已产生真实数据事故：

- 2026-09-27~28，`add-knowledge-atlas`（仍在 `spec/changes/`，未归档）的全部
  21 个 run 产物被 `runs.keep=50` 归档上限按 mtime 最旧优先**物理删除**
  （fenixd.log 21 条 WARNING），SPEC 时间轴从此只剩状态转换节点、运行节点
  全部消失——而 `timeline.py` 的设计注释假设「旧 spec 的 run 产物被清理后
  时间轴仍可回看」。
- 归档上限压的是**文件数**而非 SPEC 数：本项目吞吐 67~75 文件/天，50 个
  槽位每天翻转 1.5 次，归档产物存活期不足 24 小时。
- 反向缺口：归档 50 文件中 **18 个（36%）是无主车道产物**（code-fix 14、
  admin-global 3、code-review 1）——`run_spec_part` 解析结果不匹配任何
  `spec/changes/` 下的真实 SPEC。若清理单纯挂靠 SPEC 归档，这部分将**永久
  无限堆积**（≈25 文件/天 ≈ 9000 文件/年）。

`runs.keep` 同时违反本项目「新增配置项必须带 Dashboard 界面」约定：写侧
（config_admin）、读侧（runs.py）齐备，设置页无面板，docs 零记载，项目
config.yaml 从未配置——是半成品配置项。

## What Changes

1. **取消 `runs.keep` 配置项**：删除读侧消费（`_resolve_runs_keep`）、
   config_admin 受管键/缺省回显/生效回显/写入分支中的 `runs` 键，以及
   保留清扫器中「归档目录按 keep 上限删除」的整段逻辑。
2. **run 产物清理挂靠 SPEC 归档**：`archive_spec_runs`（SPEC 归档时调用，
   现行为「顶层移入 archive/」）升级为**清理**——该 SPEC 的 run 产物从
   顶层与 archive/ 归档副本**一并删除**。产物生命周期从此绑定 SPEC 生命周期：
   SPEC 未归档，产物可回看；SPEC 归档，产物即清理。
3. **无主车道产物兜底清理**：保留清扫器（`runs_retention_check`）原第 2 步
   改造为「archive/ 中归属不匹配任何活跃 SPEC（`spec/changes/` 下无同名
   目录）且 mtime 超过保留天数（常量，缺省 14 天）的 `*.jsonl` 删除」，
   覆盖 code-fix / admin-global / code-review 等无显性 SPEC 的车道产物，
   保证归档目录有界。

「终态 run 移入归档」（清扫器第 1 步）原样保留——活跃目录有界性依赖它，
与本次改动无关。

## Capabilities

- `run-artifact-lifecycle`：run 产物生命周期绑定 SPEC 归档 + 无主产物兜底清理
  （ADDED，含取消 runs.keep 的行为变更）

## Impact

- **代码**：`core/dashboard/data/runs.py`（清扫器拆解、`_resolve_runs_keep`
  删除）、`core/agent_runner/run_files.py`（`archive_spec_runs` 升级为清理 +
  模块 docstring 保留语义更新）、`core/dashboard/data/config_admin.py`
  （`runs` 受管键移除）、`core/dashboard/watcher.py` / `core/admin_monitor.py`
  等注释处的 keep 语义引用更正。
- **配置**：`runs.keep` 成为死键——存量 config.yaml 中已写入的值不再被
  消费（无迁移脚本，读侧不存在即无害；docs 帮助文档如涉及则同步）。
- **行为取舍（有意变更）**：SPEC 归档后其 run 产物（LLM 对话转录）不可再
  回看，时间轴运行节点随之消失；终态 SPEC 的耗时/成本汇总已由 STATE 固化
  （`fix-dashboard-read-path-performance` 5.1b 已确认接受该类缩水）。
- **非目标**：不为无主产物保留天数引入新配置项（常量即可，将来如需可调
  再按「配置项必须带 Dashboard 界面」约定立项）；不改动 verify-progress /
  screenshots 等其他运行时产物的保留策略。
