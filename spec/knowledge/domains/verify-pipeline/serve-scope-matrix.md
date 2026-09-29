# 被测实例 serve 范围矩阵
<!-- knowledge: capability=serve-scope-matrix rev=1 sources=spec/archive/2026-09-19-fix-command-main-serve-scope -->

被测实例服务路径的 scope × kind 组合矩阵：`verify.static_scope` 与 `serve.kind` 正交，四条组合各有等价的契约实例语义，缺失组合不得静默降级 legacy。

## 现行规则

- 矩阵完备：`static×main`、`static×worktree`、`command×worktree`、`command×main` 四条组合各自提供等价的契约实例语义；任一组合缺失时不得静默降级到 legacy 兜底链。
- 契约实例语义定义：框架分配/发现被测实例端口 → 场景 URL 全量改写（origin）到该实例（BASE_URL 注入铁律）→ 就绪探针通过后放行场景。
- command × main：以主树项目根为 cwd 启动 `serve.cmd`，对场景文件执行 origin 全量改写，探测就绪后放行；不退回 `commands.start` 自启链路、不触发逐端口 `_rewrite_scenario_port`。
- 未迁移契约兼容：`serve.cmd` 未引用 `{port}`/`$FENIX_VERIFY_PORT` 而由应用自绑声明默认端口时，框架经进程归属发现定位该实例真实端口，场景 origin 全量改写到该端口，就绪探针通过后放行。
- legacy 兜底链不作无据归因：契约缺失或无效回退 legacy 兜底链时，端口改写日志如实描述「场景声明端口 ≠ 框架分配端口，已改写对齐」，不得断言「planner 臆测」等指向场景编写者的无据归因（该措辞曾产出归因错误的 SPEC 并误导自省）。

## 溯源

- [2026-09-19 fix-command-main-serve-scope](spec/archive/2026-09-19-fix-command-main-serve-scope/) — 补齐 `command×main` 组合的契约实例路径接线（此前四条组合只有三条接线，默认配置下该组合每轮静默退回 legacy 兜底、绕开 BASE_URL 全量改写铁律），并修正 legacy 段端口改写日志的无据归因措辞
