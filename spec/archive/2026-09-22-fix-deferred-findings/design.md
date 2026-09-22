# Design: fix-deferred-findings

## Context

前三条重构 spec 各自留了一份「只记录不修」的疑点清单。本设计基于对三份清单**逐条回源码核实**后的账目。

**范围澄清（重要）**：`refactor-agent-runner-module` 的疑点清单（`agent-runner-findings.md`）**零遗留**——6 条全部标「✓ 已解决」并已抽证。故本变更只处理 dashboard（4 条）+ verification（10 条）。

核实后：14 条中 **3 条建议记录不修**、**3 条落在在飞重构 spec 作业面内**（须转移）、其余 8 条可安全并行。

## Goals / Non-Goals

**Goals:**

- 清算无重叠的遗留疑点，其中 1 条 P0 真 bug（timeline 排序键）。
- 每条显式标注行为变化（零变化 / 有意修复）与测试证据。
- 与在飞重构 spec 源文件严格隔离。

**Non-Goals:**

- 不修改在飞重构 spec 的作业面文件（见 D3 转移清单）。
- 不做清单之外的改动。
- 不"顺手"重构。

## Decisions

### D1：逐条账目（分组即交付契约）

| # | 条目 | 位置（符号锚点） | 分类 | 行为变化 | 测试证据 | 在飞重叠 | 优先级 |
|---|---|---|---|---|---|---|---|
| 1 | `_timeline_sort_key` 无效时间戳抛 TypeError | `core/dashboard/data/timeline.py`::`_timeline_sort_key` | **真 bug** | **有意修复** | 改写 `test_characterization_dashboard_data.py::test_timeline_sort_key_invalid_time_sorts_later` | 无 | **P0** |
| 2 | `_port_responds` 串行探测 51 端口（两处） | `verification/serving.py`::`_serve_command_in_worktree` / `_serve_command_in_main` | 性能 | 零变化（结果集不变） | 新增 mock urlopen 并发一致性测试 | 无 | **P1** |
| 3 | 3 处重复 late-import `import re as _re` | `verification/serving.py`（2 处）、`infra_classify.py`（1 处） | 整洁 | 零变化 | 无（两个文件顶部已有 `import re`，删冗余即可） | 无 | P2 |
| 4 | `_escalate_env_blocked` evidence 截断无省略号 | `verification/escalation.py`::`_escalate_env_blocked` | 可读性 | 有意（微） | 新增 >300 字符单测 | 无 | P3 |
| 5 | `_record_verdict_adoption` token 基线静默 fallback | `verification/verdict_evidence.py`::`_record_verdict_adoption` | 健壮性 | 有意（微，仅加告警） | 新增坏 baseline → 告警用例 | 无 | P3 |
| 6 | legacy / `_read_verdict` 共享文件 fallback 路径重复 | `verification/legacy.py`、`report_gate.py` | 整洁 | 零变化 | 无 | 无 | P3 |
| 7 | `_unregister_serving_instance` 先于 `stop()` 且 except 仅 pass | `verification/serving.py`::`_ensure_serving_worktree` | 健壮性 | 有意（微，仅加日志） | 无（对齐 `_evict_spec_serving` 样板） | 无 | P3 |

**记录不修（显式登记，理由如下）：**

| 条目 | 位置 | 不修理由 |
|---|---|---|
| `_should_overlay` done/pushed 叠加语义 | `dashboard/data/tasks.py`::`_should_overlay` | 注释已自证刻意（覆盖实现者从不勾 tasks.md）；三用例已锁定现行为，语义合理 |
| `shell=True` 注入面 | `verification/serving.py`（3 处 `Popen`） | shell 展开是有意设计；信任边界 = `.fenix/verify.yaml` 写权限，属已接受风险 |
| config 缓存键（OBS-1） | `dashboard/data/config_admin.py` | `read_config` **已无缓存**（清单描述过时）；`read_effective_config` 的键含门面 `USER_CONFIG_PATH` 恰是测试期望的正确语义 |
| `max(1, base >> (attempts-1))` 位移降档（B5） | `verification/escalation.py` | 正整数上位移与向下取整除法**严格等价**，改写纯 churn；现有测试锁数值结果 |

### D2：timeline 排序键修复的连带决策

`_parse_iso_ts` 对**无时区后缀**的字符串返回 naive datetime。naive 与 aware 的 `datetime.max` 在元组首元素比较时**仍会抛 TypeError**。故单纯把 `_tz` 改为 `timezone.utc` 不彻底。

**裁决**：在 `_parse_iso_ts` 内给 naive 结果补 `tzinfo=utc`（**有意行为变化**，本变更显式标注），使「无时区戳」按 UTC 解释——与项目「全链时间戳 UTC」约定一致（见记忆 `fenixd-timestamps-all-utc`）。MUST 补测试锁定 naive 输入的解释。

**替代方案（已否决）**：只改 `_tz`。否决理由：docstring 声称「解析失败的事件按原字符串排在末尾」，而 naive-vs-aware 比较仍会抛错，修复不完整。

**下游消费点登记（评审补，2026-09-17）**：`_parse_iso_ts` 非 timeline 私有——它还经门面被 `core/dashboard/data/runs.py::_run_meta_cached` 消费：

- `runs.py:150` `real_dt = _facade._parse_iso_ts(real_start)`；随后 `real_dt.astimezone(timezone.utc).isoformat()`（`started`）与 `real_dt.timestamp()`（`duration_seconds`）。
  naive 输入下 `astimezone()/timestamp()` 按**本地时区**解释（本机 CST=UTC+8），补 `tzinfo=utc` 后按 UTC 解释 → 对**无时区后缀**的 run 首事件戳，`started` 与 `duration_seconds` 会变化（偏差恰为本地时区偏移）。
- 方向正确（与「全链时间戳 UTC」一致），但属**可观测行为变化**，故 MUST 与本条同批次显式标注，并在 tasks 1.4 的测试里对该路径补一条断言（naive 输入 → `started` 为 UTC 解释结果）。
- `runs.py:96` 仅做 `is not None` 判空，不受影响。

### D3：在飞文件隔离与转移清单

本变更 MUST NOT 修改以下在飞重构 spec 作业面文件：
`core/worktree_manager.py`、`core/pm_engine/dispatch.py`、`core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification/pipeline.py`、`core/agent_runner/runner.py`。

**在飞重叠登记（评审补，2026-09-17）**：上表隔离清单只覆盖三条重构 spec，**不足以支撑 proposal「可与前两者并行」的并行性结论**——`core/dashboard/data/timeline.py`（本变更 P0 落点）与在飞 `fix-observability-gaps` 重叠：

- `.fenix/STATE.md`：`fix-observability-gaps: status: implementing`（updated 2026-09-17T01:04）。
- `spec/changes/fix-observability-gaps/tasks.md:26`：明示「已落地（`data.py` 已拆为 `data/` 包）则按符号名在 `core/dashboard/data/timeline.py` 内修改」；`tasks.md:49`（3.1a）目标为 `get_spec_timeline` 的 Transition 去重逻辑，而 `get_spec_timeline` 与 P0 目标 `_parse_iso_ts` / `_timeline_sort_key` 同处 `core/dashboard/data/timeline.py`（`timeline.py:353` 调用 `_timeline_sort_key`，`:418` 定义 `_parse_iso_ts`）。

**处置（MUST）**：本变更 MUST 把 `core/dashboard/data/timeline.py` 登记为**跨 spec 共享文件**，实现前确认 `fix-observability-gaps` 是否已在该文件落盘：已落盘 → 基于其最新内容按符号名开工；未落盘/并行在飞 → 两者 MUST 串行（先落者 push 后，后落者 rebase 再改），MUST NOT 与其实施窗口重叠提交同一文件。P0 与 `get_spec_timeline` 去重段是不同符号，符号级无交集，冲突仅限文件级合并。

**转移清单**（落在上述文件、本变更不处理）：

| 条目 | 落点 | 转移去向 |
|---|---|---|
| CYC-1 反向 import（A3）的 `engine.py` 子项 | `core/pm_engine/engine.py` | 转移给 `refactor-facade-delegation`（其触及 engine.py）或合并后单独清理 |
| `_last_freeze_rejected*` 未声明（B4） | `verification/pipeline.py` | 转移给 `refactor-facade-delegation`（其触及 pipeline.py） |
| 陈旧 docstring D3 引用（B6） | `verification/pipeline.py` | 同上 |

**CYC-1 的非重叠子项**（`verification/escalation.py`、`verification/report_gate.py`、`dashboard/data/{runs,log_index,admin_actions,artifacts,__init__}.py`）可本变更处理：把 `get_runs` / `record_project_event` / `request_admin_invoke` / `parse_verify_progress` 搬入中性模块并由 `dashboard.data` 门面 re-export；`find_impl_run_file` / `parse_run_task_done` 直接改从 `core.run_task_track` 导入（零搬移）。**仅 engine.py 的那一行 import 转移。**

**搬迁集的两条约定（评审补，2026-09-17）**：

1. **交付面**：本搬迁落地文件为 `core/dashboard/data/{__init__,runs,log_index,admin_actions,artifacts}.py` + 新中性模块（默认 `core/signals.py`，见 Open Questions）+ 消费点 `core/event_bus.py`（`:364` `from core.dashboard.data import find_impl_run_file` 是 `find_impl_run_file` **唯一非 engine.py 侧消费点**，已登记进 tasks Deliverables）。中性模块路径 **MUST NOT** 取 `core/run_task_track.py`——该文件是在飞 `fix-robustness-edge-cases`（`status: implementing`）的登记交付物。
2. **真源内部调用点**：`get_runs` 在 `runs.py:408` 被同模块裸调用（`sum(1 for r in get_runs(project_root) ...)`），`timeline.py:247` / `summary.py:{109,266,616}` 经门面 `_facade.get_runs` 调用。搬迁 MUST 保持这些调用点可用（门面 re-export + runs.py 内改为从新模块导入），且 MUST 保持 `_RUN_META_CACHE` / `_run_meta_cached` 的 (path, mtime_ns, size) memo 语义不变——该读路径性能由已 push 的 `fix-dashboard-read-path-performance` 刚完成优化，本搬迁为纯搬移，MUST NOT 触碰其缓存判据。**登记说明**：`get_runs` / `record_project_event` 在 `core/pm_engine/` 内的唯一进口就是 engine.py:21 那一行（已转移），故这两项搬迁本身**不减少任何非 engine.py 反向 import**，属为 engine.py 子项预置中性落点；若实现阶段认为收益不足，可将其登记为「不搬」并在 findings-ledger 写明依据，MUST NOT 为达成此项而改动缓存/读路径逻辑。

### D4：不改补丁语义

所有修复 MUST NOT 引入新的模块级 patch 缝隙破坏。`re` 从未被 patch，删冗余 late-import 安全。

### D5：不使用绝对行号锚定

任务与交付物以符号名锚定。

## Risks / Trade-offs

- **[风险] timeline 修复引入 naive→UTC 解释的行为变化** → 缓解：D2 显式标注并补测试；该变化与项目 UTC 全链约定一致，方向正确。
- **[风险] CYC-1 搬迁引入导入循环** → 缓解：只搬非 engine.py 侧；`find_impl_run_file`/`parse_run_task_done` 直接改从 `core.run_task_track` 导入（真源处），零搬移。
- **[风险] 端口并发探测改变 `pre` 集** → 缓解：spec 要求逐元素一致，补一致性测试。
- **[风险] 与在飞 spec 冲突** → 缓解：D3 隔离清单；落点文件与三条重构 spec 无交集（除已转移的 3 条）。

## Migration Plan

1. 阶段 1（P0）：timeline 排序键修复 + characterization 测试同步。
2. 阶段 2（P1）：端口并发探测。
3. 阶段 3：整洁/健壮性条目（import、fallback 去重、截断标注、告警补全）。
4. 阶段 4：CYC-1 非重叠子项搬迁。
5. 阶段 5：全量回归与基线比对；疑点清单最终态汇报。

回滚：各阶段独立 commit。

## Open Questions

- CYC-1 的中性模块落点（新建 `core/signals.py` vs 并入既有模块）——默认按 **新建 `core/signals.py`** 执行（tasks Deliverables 已按此登记）；实现阶段若改并入既有中性模块，MUST 在其 `.fenix-run-result.json` findings 登记实际落点路径，且 MUST NOT 落在 `core/run_task_track.py`（在飞 `fix-robustness-edge-cases` 的登记交付物）。
