# fenix-dsh Bundle 五件套与版本钉扎

<!-- knowledge: capability=fenix-dsh-bundle rev=1
     sources=spec/archive/2026-10-30-add-fenix-dsh-bundle -->

dsh 侧的机制等价物（仓内 `dsh-bundle/`，Cordis Bundle 形态）：把 fenixd 车道依赖的 Claude 特有机制——Task 工具族、PreToolUse 三守卫、bypassPermissions 审批、模型路由、CLAUDE.md 约定载体——在 dsh 插件体系原生补齐，成对契约（prompt 写侧 ↔ fenixd 读侧）才能在 dsh 通道接通。

## 规则

- **Bundle 骨架与版本钉扎**：`dsh-bundle/` 为合法 dsh Bundle（package.json 声明 `dsh.profile`/`dsh.bundle` 字段、dsh.profile 列出 Bundle、cordis.patch.yml 为覆盖层）；peer 依赖钉 dsh 0.2.0-rc.2，只依赖官方 `@deepseek-ai/*` 包（`@dsh-cc/*` fork 发行版为已否决路线）；README 含版本兼容表（bundle 版本 ↔ dsh release）与安装/卸载命令。peer 版本不符的隔离环境中加载以明确版本错误 fail-fast，禁静默降级。
- **Task 工具族等价**：注册 TaskCreate/TaskUpdate/TaskGet/TaskList 四工具，签名对齐 claude 语义（subject/status/metadata 关键字段）；taskId 遵循 1 基创建序（读侧 run_task_track 硬约定，同一会话连续创建依次得 1、2、3）；工具调用以 `tool_call`/`tool_result` 事件发射，事件 name 与参数形状可被投影表直接消费（TaskUpdate 置 completed 时参数含 taskId 与 status=completed，与 claude tool_use block 字段名对齐）。
- **三守卫等价**：在工具执行管道上实现三个守卫，语义对齐 `.fenix/hooks/` 同名脚本——主树写守卫（消费 `FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE` 两 env，拦截对主树路径的 write/edit/bash 写入，返回「主树只读」语义错误；无 env 时直通全部写入）、读图拦截（Read 图片类目标阻断）、场景批处理（Write 场景文件校验批量约定）；守卫先于审批策略生效。
- **非交互审批**：headless/profile 形态提供全放行审批策略（等价 `--permission-mode bypassPermissions`），交互确认不阻塞无人值守运行；守卫拦截路径不受审批放行影响。
- **模型显式配置契约**：模型适配使用 OpenAI 兼容端点配置（baseurl/apikey/model 三要素），model 显式存在，缺失或为空以「模型未显式配置」错误 fail-fast，禁回退 dsh 默认档（承袭网关别名事故纪律）；配置 schema 写入 README（供 provider 链渲染）。
- **AGENTS.md 约定载体**：仓库根 `AGENTS.md` 软链指向 CLAUDE.md（单一真相源）；Bundle 经 system-prompt 分区装载工作区 AGENTS.md 内容，注入与 claude 通道等价（ADR-269 门禁裁定的 dsh 变体）；dsh 变体说明写入 Bundle README。
- **真机探针结论沉淀**：探针结论落 `dsh-bundle/docs/probe-findings.md`，五项齐备——headless `--json` 事件流样本（fixtures 落 `dsh-bundle/tests/fixtures/`，含 session/text/tool_call/tool_result/final 各类型至少一例）、stderr 错误码→分类映射建议表、usage 形态结论（可得/不可得与降级路径）、原生能力盘点（dsh-tool-todo/subagent/skill/hooks-claude-code 复用 vs 自研判定）、投影表修正建议；为 DshAdapter 的契约测试源。
- **隔离纪律**：全部测试与冒烟在 `DSH_HOME=<隔离目录>` 下进行，真实 `~/.dsh` 零写入零残留。

## 溯源

- 2026-10-30 add-fenix-dsh-bundle（spec/archive/2026-10-30-add-fenix-dsh-bundle） — 新增本能力：Bundle 五件套（Task 工具族/三守卫/非交互审批/模型显式配置/AGENTS.md 软链载体）、peer 版本钉扎与兼容表、真机探针结论五项沉淀、DSH_HOME 隔离纪律
