# 验证报告：evo-self-review-evidence-bound-attribution

> ⚠️ 本报告由框架于 2026-10-08T17:52:38Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T17:52:37.362604+00:00+run-result@mtime1791481957402548019

## 结论：✅ 通过（verified）

**状态：verified — 4/4 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 4/4 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 4 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.78M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| selfreview-template-file-attribution-discipline | 模板文件落盘验收（tasks.md 1.1）：agents/self-review.md「调查评估」段含归因证据边界纪律全文——形态层结论（未定、多假说并存）、MUST NOT 单因确定性叙事、MUST NOT 据此建议特定根因修复方向、建议转向取证/止损、证据足以裁决才给确定性归因、错误归因以新条目更正不回改历史；并回归既有核实纪律与组织顺序编号顺延。出处：spec/changes/evo-self-review-evidence-bound-attribution/tasks.md 任务 1.1，交付物 agents/self-review.md（仓库布局根目录） | pass | 0/11 | - |
| prompt-builder-selfreview-loadchain | 装载链路确认（tasks.md 2.1）：python 探针直调 core/agent_runner/prompt_builder.py:1719 _build_self_review_prompt 装载改后模板——纪律文本直达最终 prompt、五个占位符（review_date/daily_summary/todo_md_content/todo_entries/out_path）填充无残留、非交互契约段在位追加、模板缺失 fail-fast 映射（agent_prompt_path 对未知类型抛 ValueError，prompt_builder.py:307-314）不被触发且机制在场。出处：core/agent_runner/prompt_builder.py:1719-1778、:307 | pass | 0/17 | - |
| prompts-api-serves-selfreview-discipline | 服务侧模板下发验收：GET /api/prompts 返回的 self-review 条目携带归因证据边界纪律全文（origin 由框架改写到验证实例）；json_schema 校验 12 个 agent 模板全部非空可读（模板缺失 fail-fast 未触发、读失败转 500 的服务侧可观测口径）。出处：core/dashboard/routes/base.py:576（/api/prompts GET 注册）、core/dashboard/routes/settings_routes.py:256（handler 遍历 AGENT_PROMPT_FILES 读模板） | pass | 0/13 | - |
| prompts-panel-shows-selfreview-discipline | UI 展示链路验收：设置页（/#/settings，hash 路由）→「提示词」页签 → Agent 下拉切到 Self-Review（自省）→ 通用提示词只读区渲染归因证据边界纪律全文与既有核实纪律。出处：core/dashboard/static/config/config.ts:15（history hash）、core/dashboard/static/config/routes.ts:31（/settings）、core/dashboard/static/src/pages/settings/pageLabels.ts:11（提示词页签）、PromptsPanel.tsx:283（prompts-agent-switcher）、:301（prompts-generic-content） | pass | 0/12 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

