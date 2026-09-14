# 设计 — fix-command-main-serve-scope

## Context

`static_scope` 与 `serve.kind` 正交是既有决定（`docs/help/05-verification.md:58`「被测实例在哪里构建由 `static_scope` 决定」），实现却呈「三缺一」：

- `e355ff23`（契约引入）实现 static × {main, worktree}；
- `86b3b048`（full-stack command 引入）只新增 `_serve_command_in_worktree`，未补 main 侧；
- `config.template.yaml:180` 默认 `static_scope: "main"`，fenix-server 显式取 main + command。

分派点（`core/pm_engine/verification.py:832-836`）在 `command and not wt_scope` 时无 `return`，穿透到下方 legacy 探测/自启链（`:846` 起）。legacy 链只做 `commands.start` 自启与逐端口 `_rewrite_scenario_port`，不调用 `rewrite_scenarios_origin`（BASE_URL 铁律的唯一执行点在 `_finalize_static`）。

## Goals / Non-Goals

**Goals:**
- `command + main` 与其余三条组合行为一致：契约实例语义（端口注入 + BASE_URL 全量改写 + 就绪探针）。
- 消除 legacy 段的「planner 臆测」误导归因措辞。
- 最小改动：复用既有 `CommandVerifyServer` 与 `_finalize_static`，不新增端口发现逻辑。

**Non-Goals:**
- 不改变无契约项目的 legacy 兜底行为（仅日志措辞）。
- 不收紧/禁用 `command + main`（保留为受支持路径）。
- 不改变 `static_scope: worktree`（fenixd 自身）行为。

## Decisions

### D1 新增 `_serve_command_in_main`，与 worktree 版同构

`_serve_command_in_worktree`（`verification.py:519-597`）的全部逻辑——入口预检、`{port}` 替换 + `FENIX_VERIFY_PORT` 注入、`CommandVerifyServer` 构造、失败回落、serving 实例登记、`_finalize_static` 收尾——**除 cwd 与 worktree 供给外**逐行适用主树。故新方法即该方法的去 worktree 版本：

- 去掉 `_ensure_serving_worktree(...)` 调用，cwd 用 `str(self._pm.project_root)`；
- 其余（端口注入、预检、CommandVerifyServer、`_register_serving_instance`、`_finalize_static`）保持一致。
- **缓存策略：不复用、每验证新建实例**——worktree 版的 head 缓存复用段（`verification.py:535-542`）依赖「HEAD 未变 ⇒ 产物未变」这一 worktree 专属不变量，主树工作区状态比 HEAD 变化更频繁（未提交改动 + prepare 重建产物），照搬该段会测得旧产物，违背 BASE_URL 新鲜性铁律。主树版删除复用判断，但**仍以 `spec_name` 为键写入 `_contract_static_servers`**（server/mode 元数据），使 `_evict_spec_serving`（`verification.py:655-678`）在 spec 终局时能 pop 回收实例（注意不可用键 `"main"`——该键为 static 主树共享实例专属，多 spec 共享、终局豁免回收）。实例累积由既有 servers.json 登记 + daemon 周期清扫兜底（verify-process-lifecycle D6）。

**为何不在分派点内联**：保持与 `_serve_static_in_main` / `_serve_command_in_worktree` 对称的四方法结构，可读性与测试定位一致。**为何不参数化合并两方法**：worktree 版带 worktree 生命周期（重建/清理/HEAD 缓存），合并会引入条件分支增加回归面——对称复制更安全（改动面已知、逐行可对）。

### D2 分派接线：`else` 分支改为调用而非穿透

```python
if serve and serve.kind == "command" and serve.cmd:
    if wt_scope:
        return self._serve_command_in_worktree(spec_name, contract, scenarios_path)
    return self._serve_command_in_main(spec_name, contract, scenarios_path)
```

删去原 `start_cmd_override = serve.cmd; serve_port_hint = serve.port` 两行（它们仅供 legacy 链消费；command 分支已不再穿透）。contract 缺失/无 serve 时仍穿透到 legacy（预期：无契约项目零迁移）。

### D3 端口发现全复用 `CommandVerifyServer`，无需新逻辑

`CommandVerifyServer._discover_port` 三段式（注入端口精确探 → 进程归属 `ss -tlnp` by pgid → 邻近扫描）对「`{port}` 已迁移」与「未迁移固定端口」两种契约均已覆盖：

- 已迁移（`FENIX_PORT={port} node dist/server/index.js`）：注入端口精确探命中；
- 未迁移（`node dist/server.js`，应用自绑默认端口）：进程归属发现命中，无需 `{port}`。

故主树 command 路径不引入任何新端口逻辑，直接受益于既有能力。

### D4 legacy 归因措辞修正

`verification.py:963-967` 的 rewrite 日志「场景 URL 端口 X 与应用实际端口 Y 不符（planner 臆测）」→ 改为不归因措辞，如「场景声明端口 X 与框架分配端口 Y 不符，已改写对齐」。仅动字符串，不改逻辑；legacy 的 `_rewrite_scenario_port` 保留（无契约项目的兜底仍需它）。

## Risks / Trade-offs

- **[主树 command 实例与主树常驻实例并存]** → 端口注入（`find_free_port`）保证不撞端口；前端产物落主树为 `static_scope: main` 的既有语义（非本变更引入），文档已明示。
- **[未迁移契约（无 `{port}`）在主树自绑应用默认端口]** → 进程归属发现命中该实例；若应用端口已被主树常驻实例占用，实例启动即死，`CommandVerifyServer` 的 failure_note 给出诊断（既有行为，worktree 版同）。
- **[分派改动影响既有测试]** → `tests/test_verify_command_port.py` 现有用例均显式设 `static_scope=worktree`，不受影响；新增 main 用例覆盖新路径。

## Migration Plan

无数据迁移。部署即生效于使用 `command + main` 的项目（如 fenix-server）：下一轮验证起走契约实例路径。回归依赖 daemon 重启载入新代码。

## Open Questions

无。
