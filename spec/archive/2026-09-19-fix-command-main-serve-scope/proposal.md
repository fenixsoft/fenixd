# fix-command-main-serve-scope — `command + static_scope=main` 被测实例路径接线

## Why

`verify.static_scope` 被设计为与 `serve.kind` **正交**——`main`（默认）与 `worktree` 只决定被测实例「在哪构建、在哪起服务」，与 serve 形态（static/command）无关。文档如此承诺、配置模板默认取 `main`。但代码只接线了四条组合中的三条：

| serve.kind | static_scope | 实现 |
|---|---|---|
| static | main | `_serve_static_in_main` |
| static | worktree | `_serve_static_in_worktree` |
| command | worktree | `_serve_command_in_worktree` |
| **command** | **main** | **不存在** → 静默落回 legacy 兜底 |

`command + main` 的分派点（`core/pm_engine/verification.py:832-836`）在 `not wt_scope` 时**不回早退**，直接落到 `_ensure_app_reachable` 的 legacy 兜底链（`commands.start` + 逐端口改写），从而**绕开 BASE_URL 注入铁律**（`rewrite_scenarios_origin` 的两个调用点都在 `_finalize_static`，legacy 路径从不经过它）。

后果有两层：

1. **真·路径缺口**：默认配置（`static_scope: main`）+ 契约声明 `serve.kind=command` 的项目（实测 fenix-server 即此形态），每轮验证都退回 legacy：自动 `commands.start` 自启、逐端口 `_rewrite_scenario_port` 改写场景、多耗一轮环境初始化。
2. **误导性归因信号**：legacy 段的改写日志硬编码「（planner 臆测）」措辞（`verification.py:967`），把「框架分配的端口 ≠ 场景声明的端口」这一**框架侧**现象归咎于 planner。实测 fenix-server 的场景端口 `3773` 是该应用在源码中声明的默认端口（`server/index.ts:26 DEFAULT_PORT = 3773`）——planner 读的是正确值，动的端口的是框架。该假信号已实际误导每日自省、产出一份归因错误的 SPEC 并通过其 verdict（`evo-planner-port-alignment`，2026-09-14 撤销）。

## What Changes

- **新增 `_serve_command_in_main`**：与 `_serve_command_in_worktree` 同构，仅将 cwd 从 serving worktree 换为主树项目根（复用既有 `CommandVerifyServer` 三段式端口发现 + `_finalize_static` 的 BASE_URL 全量改写）。`command + main` 由此获得与其余三条组合一致的契约实例语义。
- **分派点接线**：`verification.py` 的 `if serve.kind == "command" and serve.cmd` 分支，`not wt_scope` 时改调 `_serve_command_in_main`，不再落 legacy。
- **legacy 归因措辞修正**：legacy 兜底段（仅契约缺失/无效项目才走）的端口改写日志去掉「planner 臆测」，改为如实描述「场景声明端口 ≠ 框架分配端口，已对齐」。
- **回归测试**：`tests/test_verify_command_port.py`（或新增用例）覆盖 `command + main` 走契约实例路径、`rewrite_scenarios_origin` 被调用、legacy 不再触发。

## Capabilities

### New Capabilities
- `serve-scope-matrix`: 被测实例服务路径的 scope × kind 组合矩阵——明确 `static_scope` 与 `serve.kind` 正交、四条组合各有等价契约实例语义（端口注入 + BASE_URL 全量改写），缺失组合不得静默降级 legacy。

### Modified Capabilities
<!-- 无既有 capability 的 spec 级需求变更：legacy 归因措辞属实现细节，不改变 verify 行为契约；verify.yaml 契约字段语义不变。 -->

## Impact

- **代码**：`core/pm_engine/verification.py`（新增 `_serve_command_in_main` + 分派接线 + legacy 日志措辞）。
- **测试**：`tests/test_verify_command_port.py`。
- **行为**：契约声明 `serve.kind=command` 且 `static_scope=main` 的项目，验证前实例启动改走契约链路（注入端口 + 场景 origin 全量改写 + 就绪探针），不再退回 `commands.start` 兜底；已迁移 `{port}` 与未迁移契约（进程归属/邻近扫描兜底发现）两种形态均覆盖。
- **不影响**：`static_scope: worktree` 项目（fenixd 自身）行为不变；无契约项目仍走 legacy（仅日志措辞变化）；契约字段语义不变。
- **非目标**：不改变自动启动的既有兜底行为对**无契约项目**的覆盖，不收紧 `command + main` 组合（保留为受支持路径）。
