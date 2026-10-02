<!-- knowledge: capability=project-description rev=1 sources=spec/archive/2026-09-09-add-project-description -->

# 项目简介

项目的中文简介一句话：fenix-setup 时自动生成、存于项目 config，dashboard 聚合展示，设置页可手动编辑与 AI 重新生成。

## 现行规则

- 存储位置：项目 `.fenix/config.yaml` 的 `project.description` 字段（可选，默认空）；`config.template.yaml` 含该字段说明。
- setup 自动生成：fenix-setup 流程中由执行 skill 的 Claude 会话直接阅读项目根 `README.md`（缺失或信息不足时查看 package.json、pyproject.toml 等清单文件与目录结构），生成一句约 100 字、概括项目用途的中文简介，写入 `project.description`；该步骤不引入新的脚本依赖，也不做独立的 LLM API 客户端调用。
- 兜底且不阻塞：信息不足以形成简介（空仓库、无可推断文件）或写入出错时，写入默认文案「由 Fenix 框架管理的项目，暂无自动生成的简介。」；简介生成环节的任何失败 MUST NOT 阻塞 fenix-setup 后续步骤（依赖检查、目录创建、STATE.md 初始化、daemon 启动等）。
- 聚合输出：dashboard 后端项目聚合摘要（`project_summary`，/api/projects 与 /api/overview 共用）输出 `description` 字段，取值来自该项目 config 的 `project.description`。
- 前端展示：v3 概览页项目卡片与项目列表页在项目名称旁展示简介；`description` 缺失或为空时展示占位文案，不报错。
- 设置页面板可见性：v3 设置页作用域切换为项目级（`project:<name>`）时，左侧菜单末尾自动追加一个与该项目同名的页签（与 LLM Provider 等既有页签同级）对应简介面板；用户级作用域 MUST NOT 出现任何项目同名页签。
- 手动编辑：简介面板提供文本编辑区与保存操作，保存写回当前项目 config 的 `project.description` 并同步刷新面板与项目列表展示。
- AI 重新生成：面板提供「AI 重新生成」操作，由后端接口以 headless `claude -p` 调用环境现成的 claude CLI 生成简介并保存（不实现独立的 Python LLM 客户端）；生成期间界面呈进行中状态；生成失败（超时、CLI 不可用等）提示错误并保留原值不变。

## 溯源

- 2026-09-09 add-project-description（spec/archive/2026-09-09-add-project-description） — 新增本能力：setup 自动生成与兜底规则、config 存储与模板、聚合输出与前端展示、设置页面板（项目级作用域限定）手动编辑与 AI 重新生成
