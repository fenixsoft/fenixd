# Proposal: add-project-description

## Why

Dashboard 的项目列表/项目卡片目前只能显示项目名称，用户面对多个被管项目时无法快速分辨每个项目是做什么的。项目缺少一份简短的介绍信息，且没有低成本的手段补齐。

## What Changes

- `fenix-setup` 流程新增一步：由执行 skill 的 Claude 会话直接阅读项目 `README.md`（缺失时查看 package.json/pyproject.toml 等清单文件与目录结构），生成约 100 字的中文项目简介，写入该项目 `.fenix/config.yaml` 的 `project.description` 字段。不新增脚本、不新增 LLM 客户端调用。
- 兜底规则：仓库为空/信息不足/无法形成简介时，写入默认文案「由 Fenix 框架管理的项目，暂无自动生成的简介。」；简介生成环节的任何失败都不得阻塞 fenix-setup 的后续步骤（STATE.md 初始化、daemon 启动等）。
- Dashboard 后端 `project_summary`（/api/projects、/api/overview 共用）输出 `description` 字段，取自项目 config 的 `project.description`；v3 概览页项目卡片与项目列表页展示简介。
- v3 设置页新增项目简介面板：仅当作用域切换为某个项目级时，左侧菜单末尾自动追加一个与项目同名的页签（与 LLM Provider 等页签同级）；面板内提供简介 textarea（可手动编辑并保存）与「AI 重新生成」按钮。重新生成由后端接口以 headless `claude -p` 调用环境现成的 claude CLI 完成，不实现 Python LLM 客户端；生成失败时返回错误提示并保留原值。
- `config.template.yaml` 补充 `project.description` 字段说明（默认空）。

## Capabilities

### New Capabilities

- `project-description`: 项目简介的全生命周期——fenix-setup 时自动生成（含兜底）、config 存储与模板、dashboard 后端聚合输出与前端展示、设置页内手动编辑与 AI 重新生成。

### Modified Capabilities

（无——spec/specs/ 当前无活跃 spec，本能力涉及的设置页/项目列表均为实现层复用，不改变既有 spec 级需求。）

## Impact

- `skills/fenix-setup/SKILL.md`：新增简介生成步骤与兜底规则。
- `config.template.yaml`：新增 `project.description` 注释示例。
- `core/dashboard/data.py`：`project_summary` 聚合读取项目 config 的 description。
- `core/dashboard/`：新增「AI 重新生成」HTTP endpoint（headless `claude -p`，带超时与失败兜底）。
- `core/dashboard/static/v3/src/pages/settings/index.tsx`：项目级作用域时动态追加项目同名页签。
- 新组件 `settings/components/ProjectProfilePanel.tsx`：简介编辑 + 重新生成。
- `core/dashboard/static/v3/src/pages/overview/components/ProjectCards.tsx` 与项目列表页：展示简介。
- 兼容性：`project.description` 为新增可选字段，缺失时 dashboard 展示空/占位，不影响既有配置热更新与 agent 流程。
