# Design: add-self-review-midflight-signals

## Context

自省（`core/self_review.py`）数据摘要现为五源：STATE 终态分布、runs 统计+失败样本、admin 告警与处置、fenixd.log ERROR、近 3 日 git 提交。runs 相关两源对每个 run 只读尾 3 行（`_read_run_tail(p, 3)`）做终态分类——run **中途**的过程信息（空转轮次、API 停滞、中途 error 被救回）全部不可见。

可复用底座（均已在生产验证，零改动复用）：
- `core/agent_runner/latency.py`（fix-run-latency-toolresult-parser 已归档落地）：`latency_samples_from_events(entries, parser=None)` 接受 list 或**生成器**（`iter_events` 逐条 yield），`latency_stats` 产出 rounds/median/p90/max/stall 计数，`LATENCY_STALL_SECONDS=60.0`，`_entry_is_tool_result` 统一识别契约。
- `core/dashboard/data/runs.py`：run_metrics 日志索引（`_load_run_metric_index` ∪ 轮转回退），字段含 `turns / input_tokens / output_tokens / cost_usd / duration_seconds / terminal / agent_type / spec`（runner.py `_log_run_metrics` 写入）。
- `core/self_review.py` 既有：`_collect_run_files`（并集去重）、`_in_window` / `_run_start_ts`（窗口归属）、延迟导入风格。

## Goals / Non-Goals

**Goals**
- 成功 run 的中途浪费/险情可见：量化离群、停滞、中途 error、编排层救回痕迹四类机械化信号进自省摘要。
- 自省自身开销有界：初筛零事件流读取，深扫仅限离群 run 且行数上限。
- 降噪：只进摘要不进告警（对齐 alert-noise-governance 既有决策）。

**Non-Goals**
- 不改 `_classify_run` 终态分类口径与五源摘要既有结构（只追加第六节）。
- 不做语义级「低效」判定（如空转轮次识别）——那是自省 LLM 基于机械化信号的职责；本能力只负责机械化证据采集。
- 不新增 admin 告警类型、不改 dashboard（第六节仅进自省 prompt，不做前端展示）。
- 不动 `agents/` 其他提示词与 runner 事件写入路径。

## Decisions

**D1 初筛基线 = 同 agent_type 窗口中位数 × 3，样本 < 3 跳过**
不同 agent_type 的 turns/cost 量级不可比（implementer 数十轮 vs verifier 个位数轮），全局基线必假阳性。中位数对长尾稳健（均值会被离群者自己拉高）；×3 与 LATENCY_STALL_SECONDS 同为保守倍数，宁漏勿噪。组内样本 < 3 跳过：2 个样本互为彼此的离群对照无意义。备选「固定绝对阈值」被否：阈值随模型/车道配置漂移失效（impl_run_budget_max 可配置先例）。

**D2 深扫 = 流式逐行生成器喂 `latency_samples_from_events`**
`latency_samples_from_events` 契约即接受生成器（`iter_events` 逐条 yield），逐行 `f.readline()` + 单行 `json.loads`（失败跳过）即可流式复用，无内存峰值。单行可能数 MB（assistant message 全量消息体），MUST NOT `f.readlines()` 整读。行数上限 20000（窗口长尾 run 实测量级上界，超限多为异常残留转录）+ `truncated` 标注。备选「只读尾部窗口」被否：停滞/error 分布在中段，尾窗复刻既有盲区。

**D3 救回痕迹 = fenixd.log 关键词行归集，不按 run_id 关联**
provider switched / retry / gave up / worktree 重建四类日志行的 message 均含 spec 名但 run_id 关联不统一（部分行只有 spec 名）；按关键词归组计数 + 样本已足够自省 LLM 交叉核对（摘要同时含 runs 统计与失败样本）。强行按 run_id 关联会引入第三个解析口径，收益不成比例。

**D4 采集函数落在 self_review.py 内，延迟导入 latency 模块**
对齐模块既有风格（`_run_terminal_success` 延迟导入 dashboard.data.runs 先例）：`core.agent_runner.latency` 纯函数无副作用，但自省模块加载序保持零新增顶层依赖。不新建独立模块：采集器与既有五源同属「数据摘要聚合」职责，拆文件反而割裂。

**D5 窗口口径与快照化对齐既有节**
窗口 = `[window_start, window_end]`，`window_end` 为函数入口冻结的 `datetime.now()` 快照，聚合期间不再取实时时钟（对齐 `collect_runs_stats` 既有快照化契约）。

## Risks / Trade-offs

- [初筛漏检：量化正常但过程低效的 run] → 接受项（用户已确认初筛+深扫策略）；自省 LLM 仍可经既有失败样本/admin 告警通道覆盖极端个案。倍数 3 保守可后续按实测调参（常量提取至模块顶）。
- [中位数×3 对「全组皆浪费」窗口集体失明] → 接受项：整组离群时中位基线本身被抬 高；此类情形由 turns 绝对量级（自省 LLM 可读原始数字）与既有浪费治理兜底。
- [大转录深扫拖慢自省] → 行数上限 + 仅离群 run 深扫双闸；窗口离群 run 通常 ≤ 数个。
- [关键词归集误报（日志文案变更）] → 关键词列表集中为模块常量并注释来源日志语句；文案变更时单点维护。
- [cost_usd 缺失（部分 provider 不回传）] → 该维度全组 0/缺失时跳过（spec 已定），不产假离群。

## Migration Plan

纯增量：daemon 重启后下次自省自动带第六节；无状态迁移、无配置新增、无回滚需求（回滚 = 还原 self_review.py 与提示词）。生效须 daemon 重启（daemon 旧码陷阱，人工步骤入 docs）。
