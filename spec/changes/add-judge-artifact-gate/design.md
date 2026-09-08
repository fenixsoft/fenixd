# add-judge-artifact-gate — 设计

## Context

裁决链现状：验证引擎产出 `report.json`（逐场景原始 status）→ planner-judge 读取并**增强**（非 PASS 场景补 `classification`/`evidence`/`assertion_triage`，覆盖写回 report.json）+ 写结果文件（`{vp_dir}/.fenix-run-result.json`，status ∈ verified/bug-found/scenario-repaired）→ pm_engine `_verify_verdict_evidence` 用 `validate_report` 校验，不合规走「重试 judge 一次」，二次不合规 → blocked-env + 告警。

成功判定现状：`agent_runner._execute_agent` 对全部 agent run 以**进程退出码**判成功；judge 结果文件仅在下游 `_read_planner_result` 被动读取，缺失不反推 run 失败。

事故签名（2026-09-08）：网关流截断 → 最后一条 assistant 消息句中截断但 `stop_reason=end_turn` → CLI exit 0 → 框架判 success → report.json 未增强 → validate_report 10 项违规 → 重试被 frozen 拦截 → 误计二次失败 → blocked。4 run 挂 2 次同签名。

瞬态重试通道现状：fix-provider-transient-backoff 已落地——run 失败（success=False）按 provider 瞬态分类走原地退避重试（1/3 起），不消耗 validate_report 的「重试一次」预算。

## Goals / Non-Goals

**Goals:**
- 「exit 0 但产物缺失」必须判失败并走瞬态重试，fail-closed
- judge 中途截断时，已归因场景的分类成果保留在 report.json（checkpoint）
- 不改变 validate_report 的「产物不合规 → 重试一次 → blocked」既有语义（预算分工：产物缺失=瞬态重试；产物不合规=裁决重试）

**Non-Goals:**
- 不做网关流截断的通用检测（启发式误判率高，另立项）
- 不改 fast-track 结果契约（D6 硬校验已存在）
- 不改 implementer/verifier 等其他 agent 的成功判定（它们有各自的产物门）

## Decisions

### D1: 硬门放 `_execute_agent` 成功判定处（单点，agent_type 白名单）
进程 exit 0 后，对 `agent_type ∈ {"planner-judge", "planner-plan"}` 追加产物校验：
- 结果文件路径与 prompt_builder 注入的 `{result_path}` 同源计算（`{vp_dir}/.fenix-run-result.json`，planner-plan 为 `test_scenarios.json`）——从 prompt_builder 抽取路径计算函数共用，避免双实现漂移
- 校验 = 文件存在且 `json.loads` 可解析（非空内容）；解析失败视为缺失
- 失败 → `success=False`，`error="exit 0 但结果文件缺失（judge 产物硬门）"`，落入既有瞬态退避重试（fix-provider-transient-backoff 通道原样复用，不新增重试机制）

替代方案（否决）：在 pm_engine `_verify_verdict_evidence` 前置检查结果文件——仍会把「产物缺失」算进裁决重试预算，且 judge 失败的归因晚一层，退避重试的 provider 分类信息丢失。

### D2: planner-plan 冻结复用轮豁免
场景冻结复用轮不派发 planner-plan（既有行为），硬门对其天然无影响；若未来出现「派发 plan 但不要求重写场景集」的轮次，需按 run 的注入参数区分（本期不实现，留注释锚点）。

### D3: judge prompt 逐场景 checkpoint（agents/planner-judge.md 步骤 4 改写）
- 步骤 4 改为：**每归类完一个非 PASS 场景，立即原子写回 report.json**（覆盖写整个文件——复用 verdict_check.save_report 同款 temp+rename 语义；LLM 侧即「每次 Edit/写盘只追加一个场景的 classification/evidence 后立即保存」）
- 步骤顺序调整：先对全部非 PASS 场景完成「最小增强落盘」（逐场景 checkpoint），再按复现预算分级做深入调查/复现；「先落盘再深入」写入效率纪律段
- 截断恢复语义：重试的 judge 读到的 report.json 可能含上轮部分增强——prompt 注入「已带 classification 的场景直接沿用，只补缺失场景」（与跨轮裁决缓存注入段同型）
- result_path 写入（步骤 5）保持最后一步不变——硬门要求它存在；若截断发生在步骤 5 前，run 判失败重试（符合 fail-closed）

### D4: validate_report 语义不动
产物存在但部分/全部不合规 → 既有「重试一次 → blocked」路径不变。重试 judge 的 prompt 已有违规清单注入（add-verdict-evidence-taxonomy D2），增量 checkpoint 与其正交。

## Risks / Trade-offs

- [judge 把「逐场景写回」执行成高频全文件重写，输出 token 上升] → 写回动作是 Edit/Write 单文件小 diff，25 场景上限场景下增量可控；效率纪律段限定「先全部落盘再调查」反而减少无效深潜。
- [结果文件存在但内容为空/残缺 JSON] → 硬门按解析失败=缺失处理，fail-closed。
- [硬门误伤「合法无产物」轮次] → 白名单仅 planner-judge/planner-plan 两个有明确产物契约的类型；其他 agent 不受影响。

## Migration Plan

纯加固，无数据迁移。部署 = 合并后重启 daemon。回滚 = 还原提交即可（校验是纯新增分支）。

## Open Questions

（无——产物路径同源计算、瞬态通道复用、prompt 注入段接入点均已在探索阶段确认。）
