## ADDED Requirements

### Requirement: Bundle 骨架与版本钉扎

`dsh-bundle/` MUST 为合法的 dsh Bundle（package.json 声明 `dsh.profile`/`dsh.bundle` 字段、dsh.profile 列出 Bundle、cordis.patch.yml 为覆盖层），peer 依赖 MUST 钉 dsh 0.2.0-rc.2，且 MUST 只依赖官方 `@deepseek-ai/*` 包。README MUST 含版本兼容表（bundle 版本 ↔ dsh release）与安装/卸载命令。

#### Scenario: DSH_HOME 隔离加载

- **WHEN** 以 `DSH_HOME=<隔离目录>` 创建自定义 profile 并挂载 dsh-bundle，运行 `dsh headless "回复 ok"`（假模型端点）
- **THEN** Bundle 被加载（profile 组合成功、dump-config 可见 Bundle 条目），进程按 headless 契约退出，真实 `~/.dsh` 无任何写入

#### Scenario: peer 版本不符 fail-fast

- **WHEN** 在 dsh 版本不匹配的隔离环境中挂载 Bundle
- **THEN** 加载以明确版本错误失败，不静默降级

### Requirement: Task 工具族等价

Bundle MUST 注册 TaskCreate/TaskUpdate/TaskGet/TaskList 四个工具，签名对齐 claude 语义（subject/status/metadata 关键字段），taskId MUST 遵循 1 基创建序（run_task_track.py:304-312 约定）；工具调用 MUST 以 `tool_call`/`tool_result` 事件发射，事件 name 与参数形状 MUST 可被母设计 §4.3 投影表直接消费。

#### Scenario: 1 基创建序

- **WHEN** 在同一会话内连续 TaskCreate 三条任务
- **THEN** 返回的 taskId 依次为 1、2、3

#### Scenario: 状态更新事件可投影

- **WHEN** TaskUpdate 将任务置为 completed
- **THEN** 发射的 tool_call 事件 name 为 TaskUpdate、参数含 taskId 与 status=completed，形状与 claude tool_use block 语义等价（字段名对齐）

### Requirement: 三守卫等价

Bundle MUST 在工具执行管道上实现三个守卫，语义对齐 `.fenix/hooks/` 下同名脚本：主树写守卫（消费 FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE，拦截对主树路径的 write/edit/bash 写入）、读图拦截（Read 图片类目标时阻断）、场景批处理（Write 场景文件时校验批量约定）。守卫 MUST 先于审批策略生效。

#### Scenario: 主树写入被拦截

- **WHEN** agent 会话设置两个 env 后尝试对 FENIX_RUN_PROJECT_ROOT 下文件执行 write
- **THEN** 写入被阻断并返回含「主树只读」语义的错误，worktree 内写入不受影响

#### Scenario: 无 env 时守卫不误伤

- **WHEN** 未设置两个 env（非 fenixd 派发场景）
- **THEN** 守卫放行全部写入（等价 block-main-tree-write.py 的无 env 直通行为）

### Requirement: 非交互审批策略

Bundle MUST 为 headless/profile 形态提供全放行审批策略（等价 claude `--permission-mode bypassPermissions`），交互确认 MUST NOT 阻塞无人值守运行；守卫拦截路径不受审批放行影响。

#### Scenario: 无人值守不阻塞

- **WHEN** headless 会话执行需要审批的工具调用（守卫放行路径）
- **THEN** 调用直接执行，无交互确认等待

### Requirement: 模型显式配置契约

Bundle 的模型适配 MUST 使用 OpenAI 兼容端点配置（baseurl/apikey/model 三要素），model MUST 显式存在，缺失或为空 MUST fail-fast 且错误信息含「模型未显式配置」。配置 schema MUST 写入 README（供 SPEC-3 的 provider 链渲染）。

#### Scenario: 缺 model 配置即拒绝启动

- **WHEN** 配置只含 baseurl/apikey 无 model
- **THEN** 会话创建以「模型未显式配置」错误失败，不回退 dsh 默认档

### Requirement: AGENTS.md 约定载体

仓库根 MUST 提供 `AGENTS.md` 软链指向 CLAUDE.md（单一真相源）；Bundle MUST 经 system-prompt 分区装载工作区 AGENTS.md 内容，使 ADR-269 门禁裁定在 dsh 通道以同一文件生效；dsh 变体说明 MUST 写入 Bundle README。

#### Scenario: 装载内容一致

- **WHEN** 在含 CLAUDE.md（经 AGENTS.md 软链）的工作区启动挂载 Bundle 的会话
- **THEN** system prompt 含 CLAUDE.md 正文内容（与 claude 通道注入等价）

### Requirement: 真机探针结论沉淀

探针结论 MUST 落 `dsh-bundle/docs/probe-findings.md`，至少覆盖：headless `--json` 事件流样本（fixtures 落 `dsh-bundle/tests/fixtures/`）、stderr 错误码→provider_circuit 分类映射建议表、usage 形态结论（可得/不可得与降级路径）、原生能力盘点（dsh-tool-todo/subagent/skill/hooks-claude-code 的复用 vs 自研判定）、对母设计 §4.3 投影表的修正建议。

#### Scenario: 探针产物可供 SPEC-3 消费

- **WHEN** 检查 probe-findings.md 与 fixtures 目录
- **THEN** 五项内容齐备，事件样本为真实 headless `--json` 输出（含 session/text/tool_call/tool_result/final 各类型至少一例）
