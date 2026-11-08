# systemd-env-path-hygiene 规范

## ADDED Requirements

### Requirement: env 候选稿 PATH 基线并集

`capture_env_candidate` 捕获 env 时 SHALL 对捕获源 PATH 做基线目录集检查：基线集为常见工具安装目录（`~/.local/bin`、`/usr/local/bin`、`/usr/bin`、`/bin` 等），捕获源 PATH 缺失的基线目录按序追加至候选稿 PATH 值尾部，并在候选稿中以注释留痕「已追加目录清单与原因」；捕获源 PATH 已含全部基线目录时产物与现行为逐字节一致。

#### Scenario: systemd 最小 PATH 被补齐并留痕

- **WHEN** 捕获源为 systemd 拉起进程（PATH 仅含系统目录，缺 `~/.local/bin`）
- **THEN** 候选稿 PATH 为原 PATH 追加缺失基线目录，文件头部注释列出「捕获时追加：~/.local/bin」及原因；`~/.local/bin/claude` 场景下重启后 harness 可达

#### Scenario: 完整 PATH 产物不变

- **WHEN** 捕获源 PATH 已含全部基线目录
- **THEN** 候选稿内容与引入本能力前逐字节一致，无追加注释

### Requirement: unit 模板内置保底 PATH

`render_project_unit` 渲染的 unit SHALL 包含 `Environment=PATH=<基线目录集>` 保底行：EnvironmentFile 缺席（`-` 前缀不命中）时 daemon 仍以含基线目录的 PATH 启动；EnvironmentFile 在场时其 PATH 照常覆盖保底行（systemd 加载顺序语义，既有行为不变）。

#### Scenario: 无 env 文件时保底 PATH 生效

- **WHEN** 新装 unit 且项目 `.fenix/systemd.env` 缺席，unit 启动
- **THEN** daemon 进程 PATH 含基线目录集（`~/.local/bin` 等），harness binary 可探测

#### Scenario: env 文件在场时覆盖语义不变

- **WHEN** `.fenix/systemd.env` 在场且含 PATH 行
- **THEN** 进程 PATH 以 env 文件值为准（保底行被覆盖），与 systemd 既有加载顺序一致

### Requirement: 迁移摘要 PATH 卫生可见性

迁移编排（`migrate_to_systemd.py`）的 plan 摘要 SHALL 报告捕获源 PATH 的基线检查结果（已含/已补齐目录清单），使人工审核环节对 PATH 完整性有一眼可见的判断依据。

#### Scenario: 摘要含 PATH 卫生结论

- **WHEN** 迁移执行 env 候选稿捕获
- **THEN** plan 摘要含一行 PATH 卫生结论（如「PATH 基线检查：补齐 ~/.local/bin」或「PATH 基线检查：完整」）
