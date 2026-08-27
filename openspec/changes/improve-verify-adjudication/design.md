# Design: improve-verify-adjudication

## Context

验证裁决链现状（2026-08-27 info-clear 事件实证）：

- `_check_verification_gate`（core/pm_engine.py:590）仅比对 `.fenix/verify-progress/<spec>.json` 的 done/total；`report.json` 场景结论不参与裁决。
- `_read_verifier_result`（core/pm_engine.py:614）对结果文件缺失/非法/未知 status 一律返回 None，调用方语义为「视为 verified」——fail-open。
- `_do_spec_bug_found` / `_ensure_fix_spec_files`（core/pm_engine.py:218-305）派生 fix SPEC 时只写通用 proposal/tasks 模板，不携带父 SPEC 失败场景。
- report.json 结构稳定：`{summary: {total, passed, failed}, scenarios: [{scenario_id, status, step_results, assertion_results, ...}]}`，解析可复用 core/dashboard/data.py 现有读取模式。
- 噪音与缺陷的区分依据来自本次事件的真实样本：失败场景 `no_click_interception` 步骤报「缺少 target 选择器」中断，assertion_results 为空。

## Goals / Non-Goals

**Goals**
1. verified→done 增加场景级质量门禁：fail 場景必须被分流处置后才可放行。
2. result 文件缺口从 fail-open 改为 fail-closed + Administrator 升级。
3. fix 链继承父 SPEC 回归场景并在放行时强制闭环。

**Non-Goals**
- 不重构 verifier/planner agent 本身，不改 prompt 主结构（仅在 administrator 修正通道已有能力上衔接）。
- 不回溯清理存量 pushed/done SPEC。
- 不实现报告与进度文件的双向同步（维持快照语义）。

## Decisions

1. **闸门分层：进度层保持独立，质量层新增于其上**。改动集中在 `_on_spec_verified` 组合处（pm_engine.py:147-162），新 blocker 函数 `_check_report_quality_gate(spec)` 与既有 `_task_completion_blocker` / `_check_verification_gate` 并列合并 error。备选：重写单一巨型 gate 函数——拒绝，合并式拦截文案已是现行约定且便于单独测试。

2. **噪音判定取「断言从未执行」而非「内容相似度」等启发式**。规则：场景失败且 (`assertion_results` 为空 或 `step_results` 存在 `success:false`) → 工具噪音；否则 → 产品缺陷。二者并存时按产品缺陷从严处理。备选：LLM 分类——拒绝，引入不确定性且烧 token；规则对已观测的全部失败形态足够。

3. **噪音出路走告警而非自动改场景文件**。Administrator 已有修 test_scenarios.json 的授权（2026-08-27 注入），但框架只负责把 SPEC 滞留 verified + 发 human-escalation-alerts 告警，不直接代写场景。理由：保持「框架拦截、admin 决策」的权责边界，避免框架代码里长出场景编辑器。

4. **回归清单落盘为 fix SPEC 目录内 `regression-inherit.json`**。结构 `{parent_specs: [{spec, failed_ids, unexecuted_ids}], exempted: [{scenario_id, reason, by}]}`。多级 fix 取并集写入各自目录（fix-fix- 同时引用两级来源）。豁免亦写进该文件，天然留痕、随 change 目录持久化。备选：存 STATE.md 自定义字段——拒绝，序列化仅支持 `_` 前缀标量字段，嵌套清单会膨胀状态文件。

5. **result 文件缺口的升级路径复用 alerts 基建**。`_read_verifier_result` 返回值从 `str | None` 扩为三态：有效 status / `"missing-result"` / 其它异常标记；调用方据此写 error + 触发与 blocking-check 同源的告警通道。白名单本身不变。

6. **兼容策略：无验证痕迹的 SPEC 行为完全不变**。所有新门禁均以「该 SPEC 存在 verify-progress 目录或 verifier run 记录」为前提条件，与现有进度门禁的前置判断一致，存量草稿/纯单测路径零影响。

## Risks / Trade-offs

- [验证阻塞量上升，fix 链变慢] → Administrator 处置通道要求作为本 SPEC 验收项之一实测跑通；告警含场景 id 与修正指引降低处置成本。
- [噪音判定误伤真实 bug（步骤没写断言的环境类失败恰好掩盖产品错误）] → 从严规则 + 告警必含失败详情，人工复核成本可控；后续可依据告警统计收紧规则。
- [regression-inherit.json 被 agent 误改] → 校验清单来源于父 report 重算比对，读时发现不一致即告警；不依赖文件自身完整性做安全假设。
- [多级 fix 名称解析已在 _on_spec_done 有剥前缀逻辑] → 继承计算同样基于逐级候选存在性检测，两处共享同一 helper，避免口径分叉。

## Migration Plan

纯 daemon 内行为变更，无数据迁移。上线即对新完成的验证生效；不存在结果的旧 SPEC 不受影响。回滚 = revert 提交重启 daemon。

## Open Questions

无（噪音/缺陷分流规则、豁免留痕格式已在本轮事件中由用户确认选型）。
