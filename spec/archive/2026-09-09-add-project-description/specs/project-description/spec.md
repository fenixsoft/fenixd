# project-description 规格增量

## ADDED Requirements

### Requirement: fenix-setup 自动生成项目简介

fenix-setup 流程中 SHALL 包含一个项目简介生成步骤：由执行该 skill 的 Claude 会话直接阅读项目根目录的 `README.md`（缺失或信息不足时查看 package.json、pyproject.toml 等清单文件与目录结构），生成一句约 100 字的中文项目简介，写入该项目 `.fenix/config.yaml` 的 `project.description` 字段。该步骤 MUST NOT 引入新的脚本依赖或独立的 LLM API 客户端调用。

#### Scenario: 有 README 的项目

- **WHEN** fenix-setup 在一个含实质内容 README.md 的项目中执行
- **THEN** 项目 `.fenix/config.yaml` 的 `project.description` 被写入一段约 100 字、概括项目用途的中文简介

#### Scenario: 无 README 的项目

- **WHEN** 项目根目录无 README.md，但存在 package.json/pyproject.toml 等可推断项目性质的文件
- **THEN** 会话基于这些文件与目录结构生成简介并写入 `project.description`

### Requirement: 简介生成具备兜底且不阻塞

当信息不足以形成简介（空仓库、无任何可推断文件、无法判断项目性质）或简介写入出错时，系统 SHALL 写入默认文案「由 Fenix 框架管理的项目，暂无自动生成的简介。」；简介生成环节的任何失败 MUST NOT 阻塞 fenix-setup 的后续步骤（依赖检查、目录创建、STATE.md 初始化、daemon 启动等）。

#### Scenario: 空仓库兜底

- **WHEN** fenix-setup 在一个几乎为空的目录中执行
- **THEN** `project.description` 被写入默认文案，且 setup 继续正常完成

#### Scenario: 简介步骤异常不阻塞

- **WHEN** 简介分析或写入过程中发生任何异常
- **THEN** setup 流程继续执行后续步骤并正常启动 daemon

### Requirement: 简介在 Dashboard 展示

Dashboard 后端的项目聚合摘要（/api/projects 与 /api/overview 共用）SHALL 输出 `description` 字段，取值来自该项目 config 的 `project.description`；v3 概览页项目卡片与项目列表页 SHALL 在项目名称旁展示该简介。当 `description` 缺失或为空时，前端 SHALL 展示占位文案且不报错。

#### Scenario: 配置含简介时返回并展示

- **WHEN** 某项目 config 的 `project.description` 非空，用户打开概览页或项目列表页
- **THEN** 对应项目条目展示该简介

#### Scenario: 简介缺失时占位

- **WHEN** 某项目 config 无 `project.description` 字段或为空
- **THEN** 接口返回空值，前端展示占位文案，页面无异常

### Requirement: 设置页项目简介面板仅项目级作用域可见

v3 设置页在作用域选择为某个项目级（project:<name>）时，SHALL 在左侧菜单末尾自动追加一个与该项目同名的页签（与 LLM Provider 等既有页签同级），对应项目简介面板；作用域为用户级时 MUST NOT 出现该页签。

#### Scenario: 选择项目级作用域

- **WHEN** 用户在设置页将作用域切换为「项目级：X」
- **THEN** 菜单末尾出现名为 X 的页签，点击后展示项目简介面板

#### Scenario: 用户级作用域不出现

- **WHEN** 作用域为「用户级」
- **THEN** 菜单中不存在任何项目同名页签

### Requirement: 项目简介手动编辑

项目简介面板 SHALL 提供简介文本编辑区与保存操作，保存后写入当前项目 config 的 `project.description` 并刷新展示。

#### Scenario: 手动编辑并保存

- **WHEN** 用户在简介面板修改文本并点击保存
- **THEN** 该项目 config 的 `project.description` 更新为新文本，面板与项目列表展示同步刷新

### Requirement: AI 重新生成项目简介

项目简介面板 SHALL 提供「AI 重新生成」操作，由后端接口以 headless `claude -p` 调用环境现成的 claude CLI 生成简介并保存（不实现独立的 Python LLM 客户端）。生成期间界面 SHALL 呈现进行中状态；生成成功后更新 config 并刷新展示；生成失败（超时、CLI 不可用等）SHALL 提示错误并保留原值不变。

#### Scenario: 重新生成成功

- **WHEN** 用户点击「AI 重新生成」且 claude CLI 调用成功返回简介
- **THEN** `project.description` 被更新为新简介，面板展示刷新

#### Scenario: 重新生成失败

- **WHEN** 后端调用 claude CLI 超时或返回错误
- **THEN** 前端提示生成失败，`project.description` 保持原值
