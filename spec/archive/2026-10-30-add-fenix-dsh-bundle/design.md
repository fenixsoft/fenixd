## Context

SPEC-1 已冻结 `HarnessAdapter` 协议与 `HarnessCapabilities`（core/agent_runner/harness/protocol.py）。本 SPEC 在 dsh 侧补齐 fenixd 车道依赖的机制等价物。dsh 一切皆插件（Cordis）：Profile 叠加 Bundle，Bundle 是配置行 + 挂载代码的分发格式（`dsh.profile` 列 Bundle、`cordis.patch.yml` 覆盖）；工具注册表（core/tools）、工具执行管道、审批策略、system-prompt 分区均可插件替换。本机 dsh 0.2.0-rc.2 已安装（母设计 §2.3），`dsh headless` 契约见母设计 §2.2。

依赖时序澄清：SPEC-1 属并行实施项（母设计 §10「SPEC-2 可与 SPEC-1 并行，接口先冻结」），本 SPEC 所称「已冻结」指接口形状在 SPEC-1 的 spec 层冻结，`core/agent_runner/harness/protocol.py` 由 SPEC-1 落地；本 SPEC 零 Python 交付物、不 import 其任何产物，与 SPEC-1 的唯一耦合点是 Task 工具事件形状与 claude 语义对齐。

成对契约是本 SPEC 的核心：fenixd 的 prompt 契约段（prompt_builder.py:1562+）要求 agent 调用 TaskCreate/TaskUpdate，读侧 run_task_track.py 解析 tool_use block——Bundle 的 Task 工具族让 dsh 通道的写侧成立，SPEC-3 的投影让读侧接通。

## Goals / Non-Goals

**Goals**
- Bundle 五件套：Task 工具族 / 三守卫 / 非交互审批 / 模型配置 / AGENTS.md 载体。
- 版本钉扎：peer 钉 dsh 0.2.0-rc.2；升级走独立 SPEC。
- 真机探针结论落文档与 fixtures（SPEC-3 的直接输入）。
- 全部测试与冒烟在 `DSH_HOME` 隔离下进行（worktree 内目录），不污染 `~/.dsh`。

**Non-Goals**
- fenixd 侧任何 Python 改动（DshAdapter 归 SPEC-3）。
- 批内并行的 dsh 实现（若探针判定原生 subagent 事件不可对齐，capabilities 声明降级串行——母设计 §5.6）。
- codex/pi 的任何映射。
- `@dsh-cc/*` 生态（已否决路线）。

## Decisions

1. **Bundle 源码放仓内 `dsh-bundle/` 子目录而非独立 repo**。理由：daemon 自举实施只能交付仓内文件；独立 repo 的版本发布/安装链是人工运维。目录内以 README 记录版本兼容表（bundle 版本 ↔ dsh release），未来拆独立 repo 是纯搬运。
2. **Task 工具族自研而非复用 `dsh-tool-todo`**：先探针核对语义（subject/status/metadata 字段、1 基创建序、事件形状）；仅当探针证明其完全对齐才复用，否则自研（默认预期自研——claude 语义的 taskId 1 基序是 run_task_track.py:304-312 的硬约定）。探针结论落 probe-findings.md，此决策允许被探针证据推翻。
3. **守卫插件挂工具执行管道而非模拟 PreToolUse**：dsh 的受控执行管道（core/tools）是官方接缝；三守卫复刻 `.fenix/hooks/*.py` 的判定逻辑（含两个 env 的消费），拦截行为返回非零/阻断结果。
4. **模型配置采用「配置文件渲染」而非 env 传递**：dsh_adapter（SPEC-3）把 provider 链渲染为 Bundle 可读的配置段（OpenAI 兼容端点 baseurl/apikey/model）；Bundle 启动时校验 model 显式存在，缺失即 fail-fast（铁律：绝不依赖 dsh 默认档，承袭 narrative 网关别名事故）。
5. **AGENTS.md 用软链**：仓库根 `AGENTS.md → CLAUDE.md`（git 原生支持 symlink），单一真相源；Bundle system-prompt 分区读工作区 AGENTS.md。ADR-269 的「门禁走入库 CLAUDE.md」裁定在 dsh 通道以同一文件内容生效，dsh 变体说明写入 Bundle README。
6. **测试全部 DSH_HOME 隔离**：`DSH_HOME=<worktree>/.dsh-test` 下创建 tui/headless 自定义 profile 加载 Bundle；不触碰真实 `~/.dsh`（其中只有官方 profile）。

## Risks / Trade-offs

- [dsh 0.2.0-rc.2 插件 API 与文档不符] → 探针先行（任务组 1）；Bundle 只依赖官方 `@deepseek-ai/*` 包并在 DSH_HOME 隔离下实测加载。
- [`--json` 截断丢工具参数] → Task 工具参数短小（subject/status/metadata）远低于 8KiB 上限；探针中实测截断边界并记录。
- [usage 不可得] → 探针结论分支：可得则投影表带 usage；不可得则 SPEC-3 按 `usage_source: unavailable` 降级，Bundle 后续加统计插件（本 SPEC 记录 path，不实现）。
- [原生 subagent 事件无法对齐 claude Task 子代理形状] → 按母设计声明降级串行，probe-findings 给出后续对齐路径。
- [软链 AGENTS.md 在 Windows 工作区失效] → fenixd 运行环境为 Linux（FenixServer），风险接受；README 记录。

## Migration Plan

仓内新增目录，无存量迁移；卸载 = 删目录 + 真实 `~/.dsh` 无残留（全程隔离）。回滚 = revert。

## Open Questions

（无——开放项全部由任务组 1 的探针在实现期内以证据关闭，结论约束 SPEC-3。）
