## Why

六类 agent 的 prompt 全部硬编码在 `prompt_builder.py`（1015 行 f-string），验证事故的教训以"追加段落"方式只增不减：已死知识（AMIS 选择器大全随 v2 删除仍占 19 行 + 2 处示例）、被管产品领域规范误入通用框架（verifier Step 3 强制回归 Stock/Notes/Calculator/Email 面板清单、云端 COS e2e、壳路由），今天 planner 78 轮全量 prefill 直接受其放大。`agents/` 目录已存在三个手写角色 md 但无代码读取——将提示词真正文件化：通用层框架管理（用户不可改），项目层用户可设置（UI 可编辑），死知识与项目知识各归其位。

## What Changes

- **通用提示词文件化**：六类 agent（implementer / verifier / planner-plan / planner-judge / fast-track / administrator）的 prompt 主体迁移到项目根 `agents/<agent-type>.md`（既有 implementer/verifier/fast-track.md 按 prompt_builder 现行 prompt 重写对齐，planner 两类与 administrator 新建），prompt_builder 改为文件加载 + 占位符替换（`{spec_name}`、`{spec_dir}`、`{scenarios_path}` 等路径变量），条件动态段（REPLAN 反馈、断点续跑、上轮 error、遗产、场景冻结、交互契约、复核清单、verdict 退回）仍由代码追加——文件缺失时派发显式报错（文件为唯一真相，不再保留内置副本）
- **项目级附加提示词**：`<项目根>/.fenix/agents/<agent-type>.md` 存在时附加在通用 prompt 末尾（「项目附加提示词」段），缺席零注入；框架代码不写入该目录
- **死知识清理**：AMIS 大全与 dark- 示例删除；verifier Step 3 面板清单改为通用表述；被管产品领域规范（COS e2e、壳路由、seed 键格式）迁出框架——写入对应被管项目的 `.fenix/agents/verifier.md`（项目不可定位则登记 findings）
- **设置界面新增「提示词」页签**：用户级视图仅展示通用提示词（只读，按 agent 切换）；项目级视图展示通用（只读）+ 项目级（可编辑保存到 `.fenix/agents/`）；fenixd 自身项目（`.fenix` 自引用）的项目级编辑禁用并提示原因
- 范围外（登记不修）：administrator prompt 的 Dashboard 运维手册段落内容本身（fenixd 自身基础设施事实）；planner prompt 瘦身/按需注入

## Capabilities

### New Capabilities
- `agent-prompt-files`: agent 提示词文件化——通用层 agents/*.md 加载与占位符契约、项目级 .fenix/agents/ 附加机制、文件缺失 fail-fast、死知识清理与迁移、设置页「提示词」页签双视图

### Modified Capabilities
（无 spec 级行为变更的既有能力）
