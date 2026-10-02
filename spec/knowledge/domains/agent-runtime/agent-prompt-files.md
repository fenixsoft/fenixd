<!-- knowledge: capability=agent-prompt-files rev=2 sources=spec/archive/2026-09-09-add-agent-prompt-files,spec/archive/2026-09-25-fix-agent-lane-efficiency -->

# Agent 提示词文件化注入

六类 agent 提示词的分层体系：通用层文件是唯一真相，项目附加层按项目注入，动态契约段由代码按状态追加。

## 现行规则

- 通用层唯一真相：implementer / verifier / planner-plan / planner-judge / fast-track / administrator 六类 agent 的 prompt 主体存于框架根 `agents/<agent-type>.md`，prompt_builder 从文件加载并替换路径占位符（`{spec_name}`、`{spec_dir}`、`{scenarios_path}`、`{result_path}`、`{report_path}`、`{progress_path}` 等）。文件缺失时派发显式报错，不回退内置字符串。
- 动态段由代码追加：条件动态段（REPLAN 反馈、断点续跑、上轮 error、遗产上下文、场景冻结、交互契约、复核清单、verdict 退回、工具调用效率、取证深度上限与输出裁剪、长任务前台有界等待）按 run 状态注入。
- 注入顺序不变式：`_task_progress_contract_section` → `_result_gate_section` → 其余段 → `_noninteractive_contract_section` → 项目级附加段；任何动态段不得插到项目级附加段之后；开关关闭或条件不满足时该段返回空串（零注入，prompt 逐字节不变）。
- 项目附加层：被管项目根 `.fenix/agents/<agent-type>.md` 存在时，其内容以「项目附加提示词」段附加在通用 prompt（含动态段）之后；缺席时零注入。框架代码不写项目 `.fenix/agents/`（仅 Dashboard API 按用户操作写入）；项目的 `.fenix/agents` 经符号链接解析为通用层 `agents/` 目录（废弃自引用软链布局）时拒绝写入（403）且读取返回空——项目通道永不触碰通用层。
- 领域知识分层：通用提示词不含特定被管项目的领域知识（特定选择器、标的代码等）；项目专属知识以项目附加提示词形式存在于对应项目。
- 设置页「提示词」页签：用户级视图只读展示七类通用提示词；项目级视图展示通用提示词（只读）与项目附加提示词（可编辑，保存写 `.fenix/agents/<agent-type>.md`）。全部项目一视同仁（含 fenixd 自身）。
- result gate 段能力事实：实现者分支声明 `ScheduleWakeup` 在非交互派发下不产生唤醒，同时明示后台 Bash 任务的完成通知真实可用（两者是两件事）、禁止用 `sleep` / 周期性 `ps` 自旋模拟等待——行为约束与 long-task-foreground-wait 契约一致。
- dist 一致性：Dashboard 前端改动后 v3 dist 重建并提交（dist 为入库产物），避免 UI 验证假阴性。

## 溯源

- 2026-09-09 add-agent-prompt-files（spec/archive/2026-09-09-add-agent-prompt-files） — 固化通用层文件化唯一真相与占位符替换、项目附加层与写保护、死知识清理迁移、设置页提示词页签
- 2026-09-25 fix-agent-lane-efficiency（spec/archive/2026-09-25-fix-agent-lane-efficiency） — 固化动态契约段注入顺序不变式与零注入语义；result gate 段保留 ScheduleWakeup 事实、行为约束改为禁自旋并明示后台 Bash 通知可用
