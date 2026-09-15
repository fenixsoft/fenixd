# Design: fix-dashboard-read-path-performance

## Context

Dashboard 读路径实测随数据量二次方衰减（本仓 220 specs / 644 run 文件）：`SummaryIndex` 在 STATE 签名变化时丢弃全部缓存并逐 spec 重扫 run 目录（冷重建 4.2s）；`/api/overview` 单请求含 74k 次 `json.loads`（1.5s）；`runs.keep` 死键导致 runs 目录无界增长。详见 proposal 的实测数据。

## Goals / Non-Goals

**Goals**：把读路径成本从 O(specs × runs) 降为 O(变更量)；`/api/overview` 降至 <100ms 量级；让 `runs.keep` 真实生效。

**Non-Goals**：不改 HTTP 响应契约；不做缓存持久化；不动写入路径。

## Decisions

### D1：增量失效而非全量重建
`SummaryIndex.get` 在 `state_changed` 时保留旧 `idx`，按 spec 的自身签名（状态/依赖）逐条判失效，只重算变化项。全量重建只留给 `idx is None` 与损坏。
**替代**：加大 TTL 延迟重建——否决，会读到陈旧数据。

**（关键约束）「自身签名」MUST 含 STATE 条目指纹，不能只比文件签名。** 现状 `_spec_dep_sigs`（`core/dashboard/data.py:2937-2978`）只收集文件签名：tasks.md、实现 worktree 的 tasks.md（仅 `entry.status == "implementing"` 时才查）、.spec.yaml、verification-report.md、specs/\*\*/\*.md、verify-progress 两个文件、.fenix/config.yaml、该 spec 的 run 产物签名；**`entry` 的内容本身不入签名**。而 `spec_summary`（`:2819-2895`）的输出大量直接由 `entry` 决定：`status`(:2844)、`priority`(:2847)、`created`/`updated`(:2848-2849)、`error`(:2850)、`reviewer_run`(:2853)、`start_after`(:2857)、`frozen_until`(:2858)、`frozen`(:2861)、`progress_phase`(:2866，取 `status == "testing"`)、`budget_override`/`budget_used`(:2832-2837)、`verify_infra_rounds`(:2891)、`infra_failure_count`(:2893)，且 `task_progress`(:2821) 以 `entry.get("status")` 为入参。

因此：**只把 `idx` 保留下来、仍按现有 `_spec_dep_sigs` 比对，会让「STATE 条目字段变化但依赖文件未变」的 spec 永远返回陈旧摘要**。可复现场景：spec 被预算闸门 / env 阻塞闸门置为 `blocked`（或自动冻结）时，tasks.md、.spec.yaml、specs/、run 产物均未变，列表页会继续按旧 `status` 渲染——这正是本条变更要避免的「读到陈旧数据」，只是来源从 TTL 换成了签名不完整。现状之所以掩盖了该缺陷，是因为 `state_changed → idx = {}` 把条目变化一并吞掉。

实现要求：把该 spec 的 `entry` 关键字段序列化为稳定指纹（至少 status / priority / created / updated / error / reviewer_run / start_after / frozen_until / frozen，以及 `_` 前缀的计数类字段如 `_impl_run_budget_used`、`_verify_infra_rounds`、`_infra_failure_count`），并入 `_spec_dep_sigs` 的返回值（宁多勿漏，与既有签名风格一致）。

### D2：目录只扫一次
`_runs_by_spec_sigs` 已把 runs/archive 的签名扫描收敛为每轮一次；`spec_summary` 改从该映射取本 spec 的文件集，`get_runs` 增加「预选文件集」入口。目录 glob 次数降为常数。

### D3：尾读 seek + 元数据 memo
`_read_run_lines` 先 `seek` 尾部窗口读；窗口不足 N 行或行长超窗时回退全量逐行读（保留既有「末行超长不得从中间截断」论证——它曾致已完成 run 被误判 running）。run 元数据按 `(path, mtime_ns, size)` memo，append-only 文件未变即零读。
**替代**：对文件做持久化索引——否决，复杂度与失效管理不值当。

### D4：`runs.keep` 挂 daemon 周期任务
参照既有 archive_check 段的挂载方式，把终态 run 移入归档并按上限清理；不新建独立线程。
**替代**：在 watcher 里清——否决，watcher 是读侧，不应有写副作用。

## Risks / Trade-offs

- [增量失效漏判导致读到陈旧摘要] → 验收含「增量结果 ≡ 全量重建」的等价性用例。
- [尾读回退分支覆盖不全导致误判] → 三输入（小文件/大文件/超长末行）等价性用例。
- [归档清理误删未终态 run] → 只清终态，单测覆盖。

## Migration Plan

分四阶段各自独立 commit：①增量失效 ②去 per-spec glob ③尾读+memo ④`runs.keep` 落地。每阶段跑全量 pytest 并复测基线指标。**回滚**：逐阶段 commit 可回退。
