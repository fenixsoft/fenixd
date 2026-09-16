# Design: add-planready-artifact-gate

## Context

2026-09-09 23:39 add-verdict-contract-singularity 新验证流程首战白烧（四层根因定案，见 proposal）：

1. planner-plan（deepseek-v4-flash）24 turns 只落盘 2/3 批场景，从未写 `.fenix-run-result.json`（`{"status":"plan-ready"}`，`agents/planner-plan.md` 第 4 步契约），exit 0 自然收工（is_error=false，非 turn 截断）。
2. runner 硬门 `_check_agent_result_artifact`（`core/agent_runner/runner.py:3111`）对 planner-plan **只查 test_scenarios.json**（注释明说「无 status 契约，仅校验可解析」）→ 放行 "succeeded"。
3. pm_engine `_read_planner_result`（`core/pm_engine/verification.py:3289`）primary 缺失 → fallback 主树共享 `.fenix/.fenix-run-result.json` → implementer 残留 status='success'（spec 同名，foreign-stamp 拦截只挡异 spec）→ 白名单外。
4. daemon 跑旧码（fix-verdict-read-failclosed 22:18 提交、daemon 10:35 启动未重启），旧版白名单外 `return None` 丢弃真实值 → ERROR「status=None」误导归因 → 降级 legacy（再烧 12.6min/$2.48，报告框架合成）。

现状代码：读侧已 fail-closed（归因真实化），但 plan-ready 契约文件仍无硬门守护、planner 出题失败仍无重试直接降级、降级合成报告仍不标注降级事实与代价。

既有可复用机制：
- `AgentArtifactGateError` + 瞬态退避重试通道（fix-provider-transient-backoff；attempt 1/3，不消耗裁决重试预算）——runner.py:1903 硬门失败即落入，**零新增机制**。
- `planner_result_path`（`core/agent_runner/prompt_builder.py:36`）——注入侧/硬门校验侧同源路径计算，防双实现漂移。
- `planner_result_status_whitelist`（prompt_builder.py:66）——fix-verdict-read-failclosed D3 白名单单一来源。
- 现版 runner 拷回前置（1917–1926）：`_run_claude` 返回后、门检前拷回 worktree `.fenix-run-result.json` 与 `_copyback_verify_progress`——planner 写 worktree 相对路径的历史行为也被覆盖。

## Goals / Non-Goals

**Goals**
- G1: planner-plan 产物硬门校验 `.fenix-run-result.json`（存在/非空/合法 JSON/顶层对象/status 合法），失败走既有退避重试通道。
- G2: 硬门归因携带真实读到的 status 值，杜绝「读到 'success' 却报 None」式归因丢失。
- G3: 降级 legacy verifier 后的框架合成报告持久化标注降级原因与被降级轮次代价。

**Non-Goals**
- 不新增独立重试机制（复用 AgentArtifactGateError 通道）。
- 不改 pm_engine 读侧 fail-closed 语义与降级判定本身（降级仍发生，只是前置拦截概率大幅提高+留痕）。
- 不处理 planner 模型升级/出题质量（add-planner-efficiency 管辖）。
- 不改 legacy verifier 行为。

## Decisions

**D1 — 硬门校验路径 = `planner_result_path(root, spec, "planner-judge")`（即 `.fenix/verify-progress/<spec>/.fenix-run-result.json`）**

与 pm_engine 读侧 primary 完全同源（同一函数计算）。备选「硬门只查 worktree 根 `.fenix-run-result.json`」被否：那是拷回源而非契约落点，planner 直接写主树绝对路径（prompt `{result_path}` 注入值）时 worktree 根无该文件，会造成健康轮次误拦。

**D2 — planner-plan 的 status 校验收窄至 `("plan-ready",)` 单值**

planner-plan 的唯一合法终态是 plan-ready；`verified`/`bug-found`/`scenario-repaired` 是 judge/verifier 词汇，出现即语义错位（implementer 残留同理发）。读侧判定本就是 `status != "plan-ready"` 即降级——硬门与读侧口径完全一致。实现为模块级常量（如 `_PLANREADY_STATUSES = ("plan-ready",)`），不复用四值白名单常量，防「judge 合法值替 plan 类型放行」。

**D3 — 降级上下文经 `verify-progress/<spec>/degrade_context.json` 传递**

pm_engine 阶段1 降级判定点（verification.py:1198–1223，已有 plan_result 的 duration/cost 与 plan_status_text 归因）落盘：

```json
{
  "reason": "Planner 未生成有效场景，status=不可读(missing: ...)",
  "run_id": "planner-plan-...-a1",
  "duration_seconds": 429.0,
  "cost_usd": 2.28,
  "degraded_at": "2026-09-09T15:39:18+00:00"
}
```

`synthesize_verification_report`（`core/verify_report.py:430`）合成时读取该文件，注入渲染；降级标注随 report.json 顶层 `degrade_annotation` 字段持久化。备选「pm_engine 实例属性传递」被否：跨阶段脆弱、不持久化、测试需 mock 实例状态；「从 STATE error 字段反解析」被否：耦合消息文案格式。文件随 spec 目录生命周期，重验成功后由降级判定点之外的路径不清理（历史留痕），但**新验证流程成功完成时删除**（覆盖旧降级事实，防陈旧标注污染后续正常报告）。

**D4 — 渲染层标注 = verification-report.md 独立小节 + report.json 字段；前端最小透出**

`render_verification_report`（纯函数）新增可选降级标注参数：合成报告头部追加「> ⚠️ 降级说明：本报告由框架合成（新验证流程 planner 阶段失败：<reason>；被降级轮次 <run_id> 烧 <X.X>min/$Y.YY）」。前端（`core/dashboard/static/src/pages/projects/detail.tsx` 报告区）条件渲染同款一行提示；无标注时零渲染。Markdown 文本随既有 react-markdown 渲染链路，无新组件。

## Risks / Trade-offs

- [硬门加严误拦健康轮次] → planner-plan.md 第 4 步契约自 09-07 版本即存在，健康轮次日志（08-27/08-29 `status=plan-ready`）证明常态写该文件；误拦代价=退避重试（分钟级）而非降级整轮 legacy（12min+），方向正确。重试仍失败 → 按既有 attempt 上限走失败路径（pm_engine 收到 `plan_result.success=False`，保持 implemented 由 full_scan 兜底）——不产生 09-09 式「succeeded 却无效产出」。
- [deepseek-v4-flash 高概率复发忘写] → 重试同 prompt 仍可能再犯；归因文案精确（D2/G2）为后续 prompt 强化或模型升级提供观测数据。本 SPEC 不治模型行为。
- [daemon 旧码陷阱复发] → 合并后必须重启 daemon 方生效（2026-09-09 事故第 4 层根因即此）；任务清单含「合并后重启 + 前后行为对照」验证步。
- [degrade_context.json 与 report.json 双文件一致性] → 降级标注只在合成路径注入（report 缺失才有合成），agent 自写报告路径不受影响；新流程成功时删文件（D3），陈旧标注风险窗口极小。

## Migration Plan

单进程内行为变更，无数据迁移。合并 → 重启 daemon（supervisor 协议）→ 下一个进入验证的 spec 自然走新硬门。回滚 = revert 提交 + 重启。
