# project-architecture-diagram — 项目架构图（archify 按需生成）

## ADDED Requirements

### Requirement: 项目详情页提供「项目架构」页签且不自动生成

项目详情页页签序列 MUST 在「测试回归」之后、「会话接入」之前插入 `key: architecture`、
`label: 项目架构` 的页签，对所有注册项目一律可用（无项目级特殊处理）。页签内容 MUST
由独立组件 `ArchitectureTab` 承载，且与 QualityTab/RegressionTab 同语义地按 `active`
门控：仅在选中本页签时发起请求，未选中零请求。系统 MUST NOT 在页面加载、页签切换、
daemon 启动等任何时机自动触发架构图生成；从未生成过时页签 MUST 展示空态文案与
「刷新架构图」按钮。

#### Scenario: 首次进入页签看到空态而非自动生成

- **WHEN** 项目从未生成过架构图，用户点击「项目架构」页签
- **THEN** 页面展示空态提示（说明需手动生成）与「刷新架构图」按钮，不发起任何生成请求，
  后端状态查询返回 `none`

#### Scenario: 页签位置与按需加载

- **WHEN** 用户打开项目详情页
- **THEN** 页签顺序为 …→ 测试回归 → 项目架构 → 会话接入 →…；未选中「项目架构」时前端
  不发出任何 architecture 相关 HTTP 请求

### Requirement: 刷新按钮触发一次性 headless claude（archify）生成

用户点击「刷新架构图」后，后端 MUST 以 `POST` 触发**后台线程**中的一次性 headless
claude 进程（`claude -p <prompt> --permission-mode bypassPermissions`，cwd=项目根，
env 同 SessionManager 口径剔除 agent-run 专用键），提示词 MUST 要求使用 archify skill
分析项目代码并产出高层**运行时**架构图，产物写至项目根 `.fenix/architecture/diagram.html`
（原子写），stdout 末尾 MUST 输出结果 marker 供判定。判定 MUST 以产物文件实际存在且
非空、并含自包含 HTML 特征为权威，MUST NOT 采信 claude 自述。POST 端点 MUST NOT 在
HTTP 线程内同步等待生成完成。

#### Scenario: 点击刷新后异步生成并落盘

- **WHEN** 用户对无在飞生成的项目点击「刷新架构图」
- **THEN** POST 立即返回受理结果，后台 spawn claude 进程执行 archify 分析；生成完成后
  `.fenix/architecture/diagram.html` 存在且状态查询返回 `ready`，响应中带生成完成时间

#### Scenario: 产物权威判定不信自述

- **WHEN** claude 进程 stdout 声称完成，但 `diagram.html` 不存在或为空或非自包含 HTML
- **THEN** 最终状态判为 `failed`（错误信息说明产物缺失/无效），MUST NOT 进入 `ready`

### Requirement: archify skill 可用性保障

spawn 前 MUST 检测 archify skill 是否已安装（探测 `$CLAUDE_CONFIG_DIR/skills/archify/`
与 `~/.claude/skills/archify/` 两处 `SKILL.md`）；缺失时 MUST 自动执行
`npx skills add tt-a1i/archify -g`（限时，超时/失败判安装失败）；安装失败时本次生成
MUST 判 `failed`，错误信息 MUST 包含可人工执行的正确安装命令。

#### Scenario: skill 缺失时自动安装

- **WHEN** 项目首次点击刷新且本机未安装 archify skill
- **THEN** 后台先执行 `npx skills add tt-a1i/archify -g`，成功后继续 spawn 生成流程，
  全程状态为 `generating`

#### Scenario: 安装失败给出人工指引

- **WHEN** 自动安装命令超时或非零退出
- **THEN** 状态判 `failed`，错误信息含 `npx skills add tt-a1i/archify -g` 原样命令文本

### Requirement: 图形态契约（8–16 组件 / 单一主路径 / 信任边界 / 说明卡片）

生成提示词 MUST 约束 archify 产出的架构图：只保留 8–16 个核心组件；突出且仅突出一条
主要路径；标出外部依赖与信任边界；辅助信息放进说明卡片而非继续增加连线；节点与说明
文字使用中文。该契约 MUST 落在提示词文本中并在产物判定时对组件数量做机械校验
（超出 8–16 范围 MUST 判 `failed`，错误信息注明组件数）。

#### Scenario: 提示词携带形态约束

- **WHEN** 后台组装生成提示词
- **THEN** 提示词文本包含：8–16 核心组件、唯一主路径高亮、外部依赖与信任边界标注、
  辅助信息进说明卡片不加连线、中文标注五项要求

#### Scenario: 组件数越界判失败

- **WHEN** 产物解析出的组件数 <8 或 >16
- **THEN** 状态判 `failed`，错误信息包含实际组件数与允许范围

### Requirement: 存储与 API 下发（iframe 沙箱渲染）

产物 MUST 按项目存于项目根 `.fenix/architecture/`（`diagram.html` + `status.json`，
均为原子写；目录属 gitignored 运行时产物）。后端 MUST 提供 3 个端点（query 传
project，走既有 mixin 形态）：`GET /api/architecture/status`（返回
`state: none|generating|ready|failed`、`generated_at`、失败原因等）、
`POST /api/architecture/refresh`（受理触发生成）、`GET /api/architecture/diagram`
（下发 diagram.html，Content-Type text/html）。前端 MUST 以
`<iframe sandbox="allow-scripts">`（不带 allow-same-origin）渲染产物。

#### Scenario: 就绪后沙箱渲染

- **WHEN** 状态为 `ready`，用户停留在「项目架构」页签
- **THEN** 页面以 `sandbox="allow-scripts"` 的 iframe 加载 diagram 端点展示交互式架构图，
  并展示生成时间等元信息与可再次点击的「刷新架构图」按钮

#### Scenario: diagram 端点对未生成项目返回可识别错误

- **WHEN** 状态为 `none` 时请求 `GET /api/architecture/diagram`
- **THEN** 返回结构化错误（非 200），前端不渲染 iframe

### Requirement: 生成生命周期治理（单飞 / 超时 / 重启残留 / 前端轮询）

同一项目同时最多一个在飞生成（per-project 单飞；在飞期间再次 POST MUST 拒绝并返回
409 语义）。生成 MUST 有超时上限（模块常数，1800 秒），到时 MUST 以进程组方式击杀
claude 及其子孙进程并判 `failed`（对齐 autodraft `start_new_session` 先例）。daemon
重启后若 `status.json` 残留 `generating` 而在飞进程已不存在，读侧 MUST 合成为
`failed`（中断），MUST NOT 永久停留在 generating。前端在 `generating` 期间 MUST
以固定间隔轮询状态（活动门控内），刷新按钮置灰并展示生成中提示；`failed` 时展示
错误信息并恢复按钮可点。

#### Scenario: 在飞期间重复点击被拒

- **WHEN** 项目已有在飞生成，前端或客户端再次 POST refresh
- **THEN** 返回 409 语义错误（不产生第二个 claude 进程），前端刷新按钮保持置灰

#### Scenario: 超时进程组击杀

- **WHEN** 生成超过 1800 秒仍未完成
- **THEN** claude 进程及其派生子进程被整组击杀，状态判 `failed` 且错误信息注明超时

#### Scenario: daemon 重启后残留 generating 被合成为中断

- **WHEN** status.json 残留 `generating` 且后台线程/进程已不在（daemon 曾重启）
- **THEN** 状态查询返回 `failed`（错误信息注明生成被中断），按钮可重新触发

#### Scenario: 失败后可重试

- **WHEN** 状态为 `failed`，用户再次点击「刷新架构图」
- **THEN** 正常受理并开始新一轮生成，旧失败原因被覆盖
