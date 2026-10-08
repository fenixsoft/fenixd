# 提案：upgrade-narrative-to-investigation

## Why

转人工裁决叙事（add-adjudication-alert-narrative）落地后两个实测缺陷使其未达「告警自解释」目标：

1. **能力缺口——只有转述没有调查**：`_build_prompt` 输入仅含机械字段原文（description/evidence/recommended_action）+ choices 快照 + STATE 三行（status/error/frozen）+ 验证报告**路径存在性**（非内容）。叙事模型拿不到报告正文、失败历史、判定轮次，结构性产不出调查结论——决策者面对「judge 重跑超上限（6/5 轮）」仍需另行询问 AI 才知道是 env 豁免握手死循环（2026-10-03 potplayer-base/android-station-port 实证，用户原话：「还要专门来问你一次才知道原因」）。
2. **可靠性崩坏**：同步单次调用 × 60s 硬超时 × 网关长尾。potplayer-base 项目 45 条告警 **0 条**带 narrative（两条 WARNING：token_budget 与 judge_rerun_cap 均超时回退）；judge_rerun_cap 冻结告警因叙事调用延迟 60.58s 才落盘（15:03:26.5 冻结 → 15:04:27.1 落盘），恰逢网关长尾窗口（同期 judge run stall 188s）。告警本就在系统异常期高发——叙事恰在必败窗口同步阻塞主链路。

原 SPEC 明确裁剪异步链路（「不做异步补叙链路」），当时假设「同步 60s 可容忍」——被上述实证推翻，属有据返工。

## What Changes

1. **证据采集器**：`adjudication_narrative.py` 增加按 signal_type 注册的证据采集器——通用采集走标准产物路径（`verification-report.md` 全文、`report.json` summary + 失败场景表含 classification 分布、`verdict_stability.json` 判定历史、`fail_history.json` 轮次演进），发射点可选注入 `facts` 结构化字段（如 judge_rerun_cap 附 judge 派发台账——内存中最全、事后难重建）；总上下文预算 16K 字符分段截断。
2. **prompt 三段改四段**：`发生了什么 / 调查结论 / 为什么需要你决策 / 决策选项`；指令从「翻译技术串」升级为「基于验证材料给出根因判断，引用具体证据」；反编造规则收窄为「材料内有据可依的因果推断必须给出，材料外事实不得编造，材料不足以定位时明说并建议查证路径」。
3. **同步生成改异步补叙**：告警先以机械文案**立即落盘**（消除裁决路径上的叙事阻塞），叙事后台生成后原子补写 `entry["narrative"]`（AdminStore append 不可变 → 补叙写独立侧车文件 `narrative/<alert_id>.json`，读侧合并渲染）；超时 60→180s、允许 2 次尝试。
4. **连续失败熔断**：叙事失败按小时计数，连续 3 次失败 → 冷却期内跳过生成（WARNING 留痕），防网关事故期每个告警白烧 180s。

## Capabilities

- `narrative-investigation-upgrade`：裁决告警叙事的调查能力（证据采集、四段结构）与可靠性（异步补叙、超时放宽、失败熔断）。

## Impact

- **改动面**：`core/adjudication_narrative.py`（采集器、prompt、异步、熔断）、`core/pm_engine/family.py` 与两个旁路发射点（facts 透传 + 异步化改接线）、`core/admin_store.py` 或读侧（侧车合并）、前端 `alert-shared.tsx`（侧车 narrative 渲染 + 「调查生成中」占位）、`core/dashboard/static/dist/index.html`（构建产物）+ 单元测试。
- **不做什么**：不改告警落盘主链路时序与结构化字段语义（choices/trigger/alert-resolve 零感知）；不做超过 2 次的重试；不改微信推送通道；不做跨项目叙事缓存。
- **风险**：侧车文件生命周期管理（告警清理时需级联）——由既有告警清理路径追加删除清单承接；异步生成期间人工已处置 → 补叙照常落盘（历史完整性优先，处置不受影响）。
