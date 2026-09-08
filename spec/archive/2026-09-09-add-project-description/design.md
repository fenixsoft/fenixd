# Design: add-project-description

## Context

- fenixd 通过 `registry.discover()` 管理多个项目，每个项目有自己的 `.fenix/config.yaml`（分层配置：用户级 `~/.fenix/config.yaml` + 项目级）。
- v3 Dashboard 后端为纯 Python HTTP server（`core/dashboard/server.py`），配置读写走 `data.py` 的 `read_effective_config` / `write_config`，写入经 `_deep_merge_managed` 白名单合并、原子写。当前受管键：llm / agents.* / gates.approve_mode / runs.keep。
- GET `/api/config` 响应中 `config["project"]` 已被 server 覆写为项目名字符串（server.py:607），简介字段不可占用该键。
- agents 均通过 claude CLI + 网关环境运行；环境内始终存在可用的 claude CLI（fenix skill 亦必然在 Claude Code 会话中执行）。
- 用户明确约束：**不实现独立的 LLM 客户端**。setup 侧由执行 skill 的会话直接生成；dashboard 侧由后端调用 headless claude CLI。

## Goals / Non-Goals

**Goals:**

- fenix-setup 产出 `project.description`（约 100 字中文简介），空仓库等异常场景有默认文案且不阻塞。
- 项目简介在概览卡片、项目列表可见。
- 设置页项目级作用域下可查看/编辑/一键重新生成简介。

**Non-Goals:**

- 不把简介喂给 planner/agents 作为上下文（仅展示用）。
- 不做简介历史版本、多语言、富文本。
- 不在用户级作用域提供简介编辑（简介是项目属性）。
- 不实现 Python LLM HTTP 客户端或新增脚本依赖。

## Decisions

**D1：setup 生成 = skill 步骤内由会话直接完成**
`skills/fenix-setup/SKILL.md` 新增步骤：读 README.md（缺失时看 package.json/pyproject.toml/目录结构），生成约 100 字中文简介，写入 `.fenix/config.yaml` 的 `project.description`（yaml 已存在则就地合并该键，不存在则跳过——config 由 fenix-init 渲染，setup 通常在其后）。兜底写默认文案，步骤整体包在 try 语义内（skill 指令层面要求"任何失败跳过本步继续"）。
- 否决脚本方案（bin/gen_description.py 走 provider 网关）：新项目 setup 时 providers 常未配置（模板中为可选注释），大概率直接兜底，体验差且引入新依赖。

**D2：存储 = 项目 `.fenix/config.yaml` 的 `project.description`**
单一来源，随项目走，复用既有分层配置与热更新机制。默认文案：「由 Fenix 框架管理的项目，暂无自动生成的简介。」`config.template.yaml` 增加注释示例字段。

**D3：API 面 = GET 响应顶层 `description` + PATCH 键 `{description: ...}`**
- `read_effective_config` 增加提取分支：`effective["project"]["description"]`（str）→ 结果顶层 `description`（缺失为 ""），避开 server 覆写的 `config["project"]` 键。
- `_deep_merge_managed` 增加 `description` 分支：写入 `merged["project"]["description"]`（保留 project 节其它键）。
- 前端 `saveConfig(project, { description })` 走既有 POST `/api/config`。
- 否决 `project: {description}` 嵌套 API 字段：与 GET 响应中 `project`（名字符串）语义冲突。

**D4：重新生成 = POST `/api/project/describe?project=<name>`，headless `claude -p`**
- 后端读项目根 `README.md`（≤8KB 截断；缺失时改读 package.json/pyproject.toml 前 4KB），拼入固定中文指令 prompt：只输出一句约 100 字的项目简介纯文本。
- `subprocess.run(["claude", "-p", prompt], cwd=项目根, timeout=120, shell=False)`——参数列表传递，README 内容不经过 shell，无注入面；env 继承 daemon（默认网关路由）。
- 成功：经 `write_config` 走 D3 路径落盘，返回 `{ok, description}`；失败（非零退出/超时/空输出）：返回 `{error}`，不改动 config。
- 前端按钮 loading 态，失败 `message.error`，原值保留。

**D5：展示与面板**
- `project_summary`（data.py:1317，/api/projects 与 /api/overview 共用）增加 `description` 字段。
- 概览 ProjectCards 与项目列表页：名称下以 `Typography.Paragraph` ellipsis 1 行展示，空值显示占位「暂无简介」。
- 设置页 `MENU_ITEMS` 由静态数组改为运行时构造：scope 为项目级时末尾 push `{key: 'project-profile', label: <项目名>}`；新增 `ProjectProfilePanel.tsx`（TextArea + 保存 + AI 重新生成）。用户级 scope 不注入该页签。移动端沿用既有横排 Menu overflowX 适配。

## Risks / Trade-offs

- [config.yaml 并发写冲突] → 全部写路径收敛到既有 `write_config`（原子写），不新增直写。
- [claude -p 网关故障/超时] → 120s 超时 + 失败返回 error，原值保留；失败不阻塞任何流程。
- [README 过长] → 8KB 截断，仅取开头（通常含项目定位描述）。
- [老项目 config 无 description 键] → 读取侧容错（""），前端占位展示；无需迁移。
- [设置页动态页签回归移动端布局] → 沿用既有 isMobile 分支，验证清单包含 PC 零回归（参照 v3 移动端适配经验：同步 matchMedia）。
- [简介展示 XSS] → React 文本节点渲染，不进 innerHTML。

## Migration Plan

无破坏性迁移。老项目无该字段 → 占位展示；需要简介的项目可重跑 /fenix-setup 或在设置页点「AI 重新生成」。回滚 = 还原读取/UI 代码，config 中残留的 `project.description` 键无害。

## Open Questions

无（生成方式已由用户确认：不实现 LLM 客户端，setup 走会话自身、dashboard 走 headless claude CLI）。
