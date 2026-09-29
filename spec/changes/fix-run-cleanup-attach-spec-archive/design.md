# Design: fix-run-cleanup-attach-spec-archive

## Context

run 产物现有两条生命周期入口，互不感知：

1. **保留清扫器** `runs_retention_check`（`core/dashboard/data/runs.py`，
   daemon 300s 周期）：① 终态 run 移入 archive/；② archive/ 按
   `runs.keep`（缺省 50）最旧优先物理删除。
2. **SPEC 归档** `archive_spec_runs`（`core/agent_runner/run_files.py`）：
   归档时把该 SPEC 顶层产物移入 archive/（只移不删）。

事故与量化数据见 proposal Why：未归档 SPEC 的产物 24h 内被 keep 淘汰
（add-knowledge-atlas 21 个产物全灭）；同时 36% 归档条目是无主车道产物，
纯挂靠归档会无限堆积。

## Goals / Non-Goals

- Goals：产物生命周期单轨化——归档前可回看、归档即清理；无主产物有界；
  `runs.keep` 配置面整体移除。
- Non-Goals：不为兜底天数引入配置项/UI；不动 verify-progress、screenshots、
  `.checkpoint.json`（只清 `*.jsonl`）等其他运行时产物；不做存量死键迁移。

## Decisions

### D1. 清理挂在 `archive_spec_runs`，不新增第三入口

`archive_spec_runs` 已是「SPEC 归档 → 产物」唯一入口（remove-auto-run-cleanup
确立，`bin/fenix_archive.py` 与 `spec_archive.py` 两条归档路径都收敛到它；
Dashboard 手工归档路由 `spec_routes.py:615` → `archive_spec` → 同链）。
把它的语义从「顶层移入 archive/」改为「顶层与 archive/ 归档副本一并删除」，
一处改动覆盖全部归档入口。签名返回值从「归档数」改为「清理数」，调用方
均为 fail-open 记日志形态，兼容。

### D2. 清扫器第 2 步改为「无主产物天龄兜底」，第 1 步原样保留

- 第 1 步（终态移入归档）保持——活跃目录有界性依赖它。
- 第 2 步替换：删除 `_resolve_runs_keep` / keep 上限逻辑，改为遍历
  `archive/*.jsonl`，`run_spec_part(stem)` 不属于活跃 SPEC 集
  （`spec/changes/` 目录名集合）且 mtime 超 `_LANE_RUN_RETENTION_DAYS = 14`
  （模块常量）时删除。无主判定**每次清扫现算**（不缓存）：SPEC 归档后其
  残留产物自动落入「无主」集，14 天内由归档清理兜底删除，双保险。
- 逐周期删除量沿用批次上限（复用 `_RETENTION_DELETE_PER_CYCLE_MAX` 语义，
  改名或保留），避免单轮 I/O 尖峰；逐文件记 INFO 日志。

### D3. 无主判定口径：`run_spec_part` ∉ `spec/changes/` 目录名集合

与既有「精确归属」口径同源（`run_spec_part` 全等，code-review item
78dc8a67623f）。`spec/archive/` 已归档 SPEC 不计入活跃集——归档 SPEC 的
残留产物按无主天龄清理，正是期望行为。扫描 `spec/changes/` 每周期一次
（目录 stat 数十量级，开销可忽略）。

### D4. `runs.keep` 配置面拆除点（全集）

- `core/dashboard/data/runs.py`：`_RETENTION_KEEP_DEFAULT`、
  `_resolve_runs_keep`、`runs_retention_check` 签名 `config` 参数保留
  （第 2 步不再需要 resolve keep，但签名稳定优先；或一并收紧，实现自定）。
  返回值契约同步收紧：result 中 `keep` 键移除——唯一调用方 `fenixd.py:903`
  为 fire-and-forget 不消费返回值，仅 `tests/test_runs_retention.py` 断言
  需同步更新。
- `core/dashboard/data/config_admin.py`：`_MANAGED_KEYS` 去除 `"runs"`、
  缺省展示 `{"runs": {"keep": 50}}`、读取回显分支（653-662）、生效回显
  分支（894-899）、写入分支（1042-1050）；另有两处同文件 runs 触点一并
  拆除（评审补录，原清单漏列）：①容器键非 dict 守卫元组中的 `"runs"` 项
  （约 :1801）——不拆则非 dict runs 补丁仍被 400 拒绝，与「该键被忽略」
  口径矛盾；②write_config 前置 runs.keep 兜底校验段（约 :2111-2119）——
  runs 退出受管键后 merged 中的 runs 只可能来自存量死键，不拆则存量非法
  值（如 `keep: true`）仍令一切配置写入 ValueError，且该段注释引用的
  `runs._resolve_runs_keep` 随本 SPEC 删除成悬空引用。
- 注释/文档语义更正：`run_files.py` 模块 docstring、`watcher.py:35/307`、
  `admin_monitor.py:3510`、`timeline.py:340` 的「旧 spec 的 run 产物被
  清理后时间轴仍可回看」更新为新语义（归档后时间轴运行节点消失）。
- 前端零改动（`runs.keep` 本无 UI）；docs/help 零记载，仅 `09-config.md`
  若实现时发现有涉及则顺手更正。

### D5. 行为取舍（显式接受）

- SPEC 归档后 LLM 对话转录不可回看，时间轴运行节点消失（状态节点来自
  fenixd.log，不受影响）。耗时/成本汇总终态 SPEC 已由 STATE 固化
  （5.1b 先例）。 SPEC 归档是低频动作且归档前全程可回看，取消 keep 后
  「活着就能查」相比现状（24h 内随机消失）是净改善。
- 无主车道产物固定 14 天——若将来需要可调，按「配置项必须带 Dashboard
  界面」约定另行立项。

## Risks / Trade-offs

- **[归档目录短期增长]** 未归档 SPEC 多且 run 量大时 archive/ 增长快于
  现状（无 keep 上限）。量化：本项目 ~75 文件/天 × 平均 ~200KB ≈ 15MB/天，
  一个 SPEC 从创建到归档的中位周期（数天）内累计 < 100MB，可接受。
  → 兜底：无主产物 14 天清理 + SPEC 归档即清理。
- **[误删活跃 SPEC 产物]** 无主判定若把活跃 SPEC 误判为无主（如
  `spec/changes/` 读取失败返回空集）会大规模误删。
  → 防御：活跃 SPEC 集扫描失败时**跳过本轮兜底清理**（fail-closed），
  仅记 WARNING。
- **[测试替身残留 keep 语义]** 测试中伪造 `runs.keep` 配置的用例在拆除后
  失效。 → 拆除时 grep 测试替身旧键（memory 先例：排水窗口单源键迁移）。

## Migration Plan

无数据迁移。存量 `config.yaml` 的 `runs.keep` 残留为死键；存量 archive/
中超龄无主产物由清扫器首轮流式清理（每周期批次上限节流）。

## Open Questions

- 无（兜底天数 14、fail-closed 防御均已定；实现中若发现第五处 keep 消费点
  按 D4 口径顺延拆除）。
