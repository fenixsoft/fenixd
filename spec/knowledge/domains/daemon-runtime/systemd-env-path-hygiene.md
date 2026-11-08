# systemd env 捕获 PATH 卫生

<!-- knowledge: capability=systemd-env-path-hygiene rev=1
     sources=spec/changes/add-dispatch-precheck-true-fallback -->

EnvironmentFile 环境承载的 PATH 卫生层：捕获稿基线并集补齐、unit 模板保底 PATH、迁移摘要卫生结论——新项目 systemd 托管从第一天起 PATH 完整，坏 PATH 不再被捕获固化进重启循环。

## 规则

- **env 候选稿 PATH 基线并集**：`capture_env_candidate` 捕获 env 时对捕获源 PATH 做基线目录集检查（基线集为模块常量 `PATH_BASELINE_DIRS`：`~/.local/bin`、`/usr/local/bin`、`/usr/local/sbin`、`/usr/bin`、`/bin`、`/usr/sbin`、`/sbin`；缺失判定单源 `path_baseline_missing`，migrate 摘要与 daemon 启动自检共用）；捕获源缺失的基线目录按序追加至候选稿 PATH 值尾部（尾部仅回退语义，不改变既有目录优先级），候选稿以注释留痕「已追加目录清单与原因」；捕获源 PATH 已含全部基线目录时产物与无此机制时逐字节一致（无追加注释）。比较与写入 MUST 使用展开后的绝对路径——systemd `Environment=` 与 EnvironmentFile 值均不展开 `~`，字面 `~` 目录项会使 PATH 静默失效（`~/.local/bin` 仅为文档记法）。
- **unit 模板内置保底 PATH**：`render_project_unit` 渲染的 unit 含 `Environment=PATH=<基线目录集展开绝对路径>` 保底行——EnvironmentFile 缺席（`-` 前缀不命中）时 daemon 仍以含基线目录的 PATH 启动，harness binary 可探测；env 文件在场时其 PATH 照常覆盖保底行（systemd 加载顺序语义，既有行为不变）。
- **迁移摘要 PATH 卫生可见性**：迁移编排的 plan 摘要报告捕获源 PATH 的基线检查结论（「完整」或「补齐 <目录清单>」），人工审核环节对 PATH 完整性一眼可判。

## 关键行为

新项目出生即 systemd 托管时，env 候选稿唯一可捕获的在跑进程就是 systemd 拉起的最小 PATH supervisor：基线并集把缺失目录补进候选稿并留痕，坏 PATH 不再原样落盘、被 unit 每次重启加载（捕获自吞噬循环闭合）。已固化坏 PATH 的存量项目不靠重捕获（幂等跳过会固化），由 daemon 启动自检自愈链路修复（见 [派发前置 harness 可达性自检](../dispatch-scheduling/dispatch-precheck.md)）。

## 代码锚点

- 主实现：`core/systemd_hosting.py`（基线常量、PATH 追加与候选稿留痕、unit 模板保底行）
- 单源符号：`core/systemd_hosting.py:PATH_BASELINE_DIRS`、`core/systemd_hosting.py:path_baseline_missing`、`core/systemd_hosting.py:apply_path_baseline`
- 消费方：`bin/migrate_to_systemd.py`（捕获接入与迁移摘要卫生结论）、`fenixd.py`（启动自检告警共用判定）
- 守卫测试：`tests/test_systemd_env_path_hygiene.py`（最小 PATH 补齐留痕、完整 PATH 逐字节不变、unit 保底行无字面 ~、迁移摘要结论行）

## 溯源

- 2026-11-08 add-dispatch-precheck-true-fallback（spec/changes/add-dispatch-precheck-true-fallback/） — 新建本能力：捕获稿 PATH 基线并集（展开绝对路径、尾部追加留痕、完整 PATH 产物不变）、unit 模板保底 `Environment=PATH`、迁移摘要 PATH 卫生结论行
