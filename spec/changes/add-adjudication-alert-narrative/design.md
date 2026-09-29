# 设计：add-adjudication-alert-narrative

## Context

转人工裁决告警由 `freeze_for_human`（core/state_machine.py:1302，纯机械单一入口）携带 f-string 拼装的 description/evidence 落入各发射点，最终全部汇聚到 `pm_engine._send_human_escalation_alert`（core/pm_engine/family.py:975）写 AdminStore；choices 快照亦在此处按 `choices_for(signal_type)` 附加。另有两个旁路点自行附带 choices：core/worktree_manager/mergeback.py:476、core/agent_runner/token_budget.py:257。前端告警区（core/dashboard/static/src/components/alert-shared.tsx 等）渲染 description/evidence 与 choices 下拉。

2026-09-29 实证：决策者面对 `升级闸门连续失败第 4 轮` + `failure_profile=round1:real-bugs;...` 无法独立决策，需另行询问 AI。冻结决定必须留在机械闸门（预算/计数安全判断不依赖 LLM 存活），但**说明文本**可以在落盘时刻由 LLM 生成。

## Goals / Non-Goals

- Goals：告警自解释（三段式）；覆盖全部桶 2 发射点；失败 fail-open；配置可控且有 UI。
- Non-Goals：不改闸门判定/冻结逻辑；不改 alert-resolve 动词分派与闭环判定；不给桶 0 加叙事；不做异步补叙；不动微信推送；不加新配置面板（复用 SystemPanel）。

## Decisions

### D1 接线位置：写入口 + 共享辅助模块，不动 state_machine

新建 `core/adjudication_narrative.py`：`build_narrative(entry_ctx) -> str | None`（采集上下文 → 组 prompt → 单次 LLM 调用 → 校验三段结构）与 `attach_narrative(entry, ...) -> None`（成功时写 `entry["narrative"]`，失败静默回落）。接线点：

- `_send_human_escalation_alert`：store.append 前调用（choices 非空才发起）；
- mergeback.py / token_budget.py 旁路点：同样 append 前调用，复用同一模块，禁止第二套 prompt。

理由：`_send_human_escalation_alert` 是全部 ESCALATION 告警的共同写入口（family.py:1021 注释明言），在此一处接线即覆盖六个族；state_machine 保持零 LLM 依赖（低层可测性）。

### D2 LLM 通道：复用既有 agent 派发通道（`claude -p` 单发）

模型回退链：`admin.narrative_model` → `admin.agent_model` → 框架默认网关模型。经既有 spawn 通道做一次非交互单发（带硬超时），MUST NOT 传 `--max-tokens-budget` 类危险旗标（fenixd 实测 7/8 failed 禁传项）。不直连网关 HTTP——避免第二套凭据/UA/代理面（CF 1010 UA 误拦教训）。

通道经依赖注入（模块级 `set_channel()` 或传参），生产接 claude spawn，测试注入假通道，测试 MUST NOT 真调网关（用户级配置敏感测试先例：patch 配置源，不落 HOME）。

### D3 prompt 输入与输出契约

输入（全部 fail-open 采集，读不到就不带）：description/evidence/recommended_action/choices 快照（id+label+desc）+ STATE 条目（status/error/frozen）+ 验证报告路径存在性。输出：纯 Markdown 三段（段落标题固定「发生了什么」「为什么需要你决策」「决策选项」），无 JSON 包裹；生成后机械校验三段标题齐全，缺失视为失败走兜底。

narrative 字段形态（机器可溯源）：`entry["narrative"] = {"text": <三段 Markdown>, "model": <实际模型>, "at": <UTC ISO>}`。

### D4 失败兜底：至多一次、硬超时、WARNING 留痕

异常/超时/空输出/结构校验失败 → 不写 narrative，照常落盘，logger.warning 一条；MUST NOT 重试超过一次、MUST NOT 抛出穿透发射链路。超时 = `admin.narrative_timeout_seconds`（缺省 60）。

### D5 前端：证据前渲染，缺字段零扰动

alert-shared.tsx 在 evidence 区块之前渲染 narrative.text（复用既有 Markdown 渲染组件，默认展开）；`services/dashboard.ts` 告警类型加可选 `narrative` 字段；无该字段时 DOM 结构与现状一致（无空壳容器）。choices 下拉/执行按钮逻辑不动。

### D6 配置三键 + SystemPanel UI

`admin.narrative_enabled`（true）/ `admin.narrative_timeout_seconds`（60）/ `admin.narrative_model`（空=回退链）入 config.template.yaml admin 段（带中文注释，tracked 文件有交付先例）；SystemPanel 出三控件走既有保存通道。

读取口径分侧约定（评审补注 spec-review 2026-09-29）：dashboard 设置页侧沿用 `_cached_config_value` 口径（30s mtime 缓存热更新）不受影响；但 `_cached_config_value` 是 dashboard data 层私有函数（core/dashboard/data/summary.py:189），`core/adjudication_narrative.py` 属 pm_engine 侧新模块，MUST NOT 反向导入——统一走 pm_engine 既有口径 `ConfigLoader.get_admin_config(self._pm.config).get("narrative_*", 缺省)`（先例 family.py:563、recovery.py:1081），热更新经 daemon 主循环 `_maybe_reload_config` 每轮刷新 `self.config` 生效（fenixd.py:865），与 spec「设置页可编辑叙事配置」场景的热更新断言一致。

## Risks / Trade-offs

- **同步调用延迟**：转人工是低频事件，≤60s 可接受；开关可整体关闭。→ 硬超时 + 缺省值保守。
- **LLM 幻觉/误导**：叙事标注「建议倾向为参考」；结构化字段不被改写，裁决执行链零感知，最坏退化为「文案不好读」。
- **evidence 内容进入 prompt**：均来自本仓 STATE/报告，无跨边界数据；输出仅作展示层渲染。
- **网关不可用放大冻结期**：fail-open 保证告警即时落盘，与现状无差。

## Migration Plan

纯增量字段与新增模块，无存量数据迁移；存量告警（无 narrative）按缺字段渲染，零回填。

## Open Questions

无（机制/覆盖面/模式/时机已由用户定：闸门同步内联 LLM + 全覆盖 + full + 立即执行）。
