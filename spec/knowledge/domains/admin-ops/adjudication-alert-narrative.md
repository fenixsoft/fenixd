# 转人工裁决告警叙事

<!-- knowledge: capability=adjudication-alert-narrative rev=1
     sources=spec/archive/2026-10-06-add-adjudication-alert-narrative -->

转人工裁决告警的人类可读说明层：告警落盘同一时机经一次轻量 LLM 调用生成三段式叙事（发生了什么 / 为什么需要你决策 / 决策选项），让决策者不必解读技术串即可独立裁决，缩短冻结窗口。

## 规则

- 适用范围：携带 `choices` 的桶 2 真裁决信号写告警时生成叙事；桶 0 知情/自愈类信号（choices 为空）不发起叙事调用，记录不含 `narrative` 字段。叙事是纯增强字段：不改写 description/evidence/recommended_action/choices/trigger 任一字段的结构化语义，机器消费方（alert-resolve、闭环判定、Administrator 处置）零感知，不参与动词分派与闭环判定。
- 三段固定结构：`narrative` 为 Markdown，段落标题依次为「发生了什么」「为什么需要你决策」「决策选项」，顺序固定、缺一即视为生成失败走兜底。「发生了什么」把技术串（如 `failure_profile=round1:real-bugs`）翻译为因果白话并指明信号主体（spec、闸门、轮次）；「为什么需要你决策」说明自动链已尝试的路径、停止原因（哪条计数器/预算/闸门到顶）与放任自动继续的代价；「决策选项」对 choices 快照逐 id 给出含义、执行后果与建议倾向（倾向标注为参考，最终由人决定）。字段形态：`{"text": <三段 Markdown>, "model": <实际模型>, "at": <UTC ISO>}`。
- 覆盖面：全部桶 2 发射点——汇聚写入口 `pm_engine._send_human_escalation_alert`（覆盖预算耗尽/升级闸门/评审两族/judge 重跑上限/同因重派熔断/恢复期回调）与两个旁路 choices 附带点（mergeback 的 build_artifact_paths_missing、token_budget）。旁路点复用同一叙事辅助模块（`core/adjudication_narrative.py`），禁止内联第二套生成逻辑或第二套 prompt。
- kind 口径分侧：汇聚点与 token_budget 记录为 kind=ESCALATION，进前端告警区渲染叙事；build_artifact_paths_missing 记录为 kind=SIGNAL，不进前端告警区，其 narrative 仅要求字段落盘供消费侧读取，无渲染要求。
- 失败兜底 fail-open：LLM 异常/超时/空输出/三段结构校验不过时，告警以机械文案照常落盘（不写 narrative 字段），至多尝试一次、不阻塞发射链路、日志记 WARNING；同步调用总耗时受 `admin.narrative_timeout_seconds` 硬超时约束。叙事是增强不是门禁：冻结与升级决定权独占于机械闸门，安全判断不依赖 LLM 存活。
- 配置三键（admin 段入 config.template.yaml，设置页 SystemPanel admin 作用域出可编辑控件，保存走既有配置保存通道热更新生效）：`admin.narrative_enabled`（bool，缺省 true，关闭时零 LLM 调用零额外延迟、行为与无叙事基线一致）；`admin.narrative_timeout_seconds`（int，缺省 60，同步调用硬超时秒数）；`admin.narrative_model`（str，缺省空=回退 `admin.agent_model`，仍空=复用框架默认模型）。pm_engine 侧读取统一走 `ConfigLoader.get_admin_config(...)` 取 `narrative_*` 键（经 daemon 主循环每轮配置重载生效），不反向导入 dashboard data 层的私有缓存函数。
- LLM 通道：经既有 agent spawn 通道做一次非交互单发（带硬超时），不直连网关 HTTP、不引入第二套凭据/UA/代理面；通道经依赖注入可替换，测试注入假通道，不真调网关。
- 前端渲染：告警区在 evidence 之前渲染 narrative 三段式（Markdown 渲染、默认展开），长文本按既有序列化容器规则折叠/滚动展示，不横向溢出、不遮挡 choices 操作区；记录无 narrative 字段时渲染与现状一致（无空壳区块）；choices 下拉与执行按钮交互不变——叙事只承载可读性，不承载机器语义。

## 溯源

- 2026-10-06 add-adjudication-alert-narrative（spec/archive/2026-10-06-add-adjudication-alert-narrative） — 新增本能力：写入口+旁路点全覆盖接线、三段结构契约与字段形态、fail-open 兜底、三配置项与 SystemPanel UI、告警区证据前渲染
