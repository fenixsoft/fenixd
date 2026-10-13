## Why

多 harness 母设计（`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md`）确定以「能力等价映射、只做 dsh」方式接入 DeepSeek Harness：fenixd 侧依赖的 Claude 特有机制（Task 工具族、PreToolUse 三守卫、bypassPermissions 审批、模型路由、CLAUDE.md 约定载体）必须在 dsh 侧用其插件体系（Cordis Bundle）原生补齐，成对契约（prompt 写侧 ↔ fenixd 读侧）才能在 dsh 通道接通。本 SPEC 是依赖链第二环，交付 fenix-dsh Bundle 与真机探针结论，依赖 SPEC-1 冻结的 `HarnessCapabilities` 接口。

## What Changes

- 新增仓内 `dsh-bundle/` 包（TypeScript，Cordis Bundle 形态：package.json + dsh.profile + cordis.patch.yml），peer 依赖钉 dsh 0.2.0-rc.2。
- Task 工具族插件：注册 TaskCreate/TaskUpdate/TaskGet/TaskList 四工具，签名对齐 claude 语义（subject/status/metadata），保证 1 基创建序约定，事件发射形状符合母设计 §4.3 投影表输入。
- 三守卫插件（挂 dsh 工具执行管道）：主树写守卫（消费 `FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE`）、读图拦截、场景批处理，语义对齐 `.fenix/hooks/*.py` 三个 PreToolUse 脚本。
- 非交互审批策略插件：headless 全放行，主树守卫先行拦截（等价 bypassPermissions）。
- 模型适配器配置：OpenAI 兼容端点接入 + 配置 schema（承接 fenixd provider 链 name/baseurl/apikey/model 渲染）；模型必须显式配置、无默认档回退。
- 项目约定载体：仓库根新增 `AGENTS.md`（软链至 CLAUDE.md），Bundle system-prompt 分区装载验证；ADR-269 门禁载体裁定的 dsh 变体说明。
- 真机探针（DSH_HOME 隔离）：headless `--json` 事件流 fixtures、stderr 错误码表、usage 形态结论、原生能力盘点（dsh-tool-todo/subagent/skill/hooks-claude-code 复用 vs 自研判定）、投影表修正建议——产出 `dsh-bundle/docs/probe-findings.md` 供 SPEC-3 消费。

## Capabilities

### New Capabilities
- `fenix-dsh-bundle`: fenix-dsh Bundle 的工具族/守卫/审批/模型配置/载体五件套与版本钉扎契约。

### Modified Capabilities

（无——本 SPEC 不改 fenixd 任何既有需求；探针结论对投影表的修正以文档形式供 SPEC-3 采纳。）

## Impact

- 新增目录：`dsh-bundle/`（源码/测试/docs）；仓库根 `AGENTS.md` 软链。
- 不改 fenixd core（零 Python 交付物）；测试经 `DSH_HOME` 指向 worktree 内隔离目录，不污染真实 `~/.dsh`。
- 对下游：SPEC-3 依赖本 SPEC 的 Bundle 发布物、探针 fixtures 与投影表修正建议。
- 已否决路线（勿重试）：`@dsh-cc/*` fork 发行版（母设计 §2.3）；Bundle 只依赖官方 `@deepseek-ai/*` 包。
