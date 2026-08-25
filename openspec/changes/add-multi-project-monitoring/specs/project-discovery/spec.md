## ADDED Requirements

### Requirement: 默认自动扫描发现 Fenixd 项目

`Registry.discover()` MUST 以自动扫描为主发现被监控项目：当 `~/.config/fenixd/dashboard.yaml` 未配置 `scan_dirs`（或为空）时，MUST 默认将用户主目录（`~`）作为唯一扫描根，遍历其一级子目录，仅当子目录同时存在 `STATE.md` 与 `.fenix/config.yaml` 才将其识别为 Fenixd 项目并纳入监控列表。显式配置 `scan_dirs` 时 MUST 沿用该配置作为扫描根（覆盖默认）。显式 `projects` 中的项目 MUST 始终出现在监控列表（即使扫描未命中或目录不存在，标记 `exists=False`）。扫描结果与显式注册按规范化路径去重。

#### Scenario: 默认扫描主目录发现多个项目
- **WHEN** `dashboard.yaml` 未配置 `scan_dirs`，且主目录一级子目录 `~/projectA`、`~/projectB` 各含 `STATE.md` 与 `.fenix/config.yaml`
- **THEN** 监控列表同时包含 `projectA` 与 `projectB`，并标记为自动发现（`discovered=true`）

#### Scenario: 非 Fenixd 目录被排除
- **WHEN** 主目录一级子目录 `~/not-a-project` 只有 `STATE.md` 而无 `.fenix/config.yaml`
- **THEN** 该目录不进入监控列表

#### Scenario: 显式注册与扫描结果去重
- **WHEN** `projects` 显式注册了 `~/projectA`，且默认扫描也发现 `~/projectA`
- **THEN** 监控列表中 `projectA` 只出现一次

### Requirement: 显式注册为扫描的补充

框架 MUST 保留显式注册途径作为自动扫描的补充：`Registry.add_project(path)` 将项目写入配置 `projects`（按规范化路径去重，已存在则跳过），供 `bin/fenix_dashboard.py --add-project` 与 `/fenix-dashboard` skill 调用；扫描不到的路径（如非主目录下项目）可通过显式注册纳入监控。

#### Scenario: 非扫描范围内的路径可显式注册
- **WHEN** 一个含 `STATE.md` 与 `.fenix/config.yaml` 的项目位于扫描范围（默认 `~` 或 `scan_dirs`）之外，用户执行 `--add-project <path>`
- **THEN** 该项目被写入配置并出现在监控列表，标记为非自动发现（`discovered=false`）

#### Scenario: 重复注册被跳过
- **WHEN** 对已注册的项目路径再次执行 `--add-project`
- **THEN** 配置中不产生重复条目，返回已存在的提示

### Requirement: 移除已注册项目

`Registry.remove_project(path)` MUST 将显式注册的项目从配置 `projects` 中移除（按规范化路径匹配）并写回；若该路径未在配置中显式注册（包括仅由扫描自动发现的项目），MUST 返回未变更提示且不报错。`bin/fenix_dashboard.py` MUST 提供 `--remove-project <path>` 子命令调用该能力，用于清理残留/不再监控的项目。

#### Scenario: 移除已注册项目
- **WHEN** 执行 `--remove-project <path>`，且该路径存在于配置 `projects`
- **THEN** 该条目从配置中删除，监控列表不再包含它（除非扫描仍自动发现）

#### Scenario: 移除未注册项目不报错
- **WHEN** 执行 `--remove-project <path>`，且该路径未在配置中显式注册
- **THEN** 返回未变更提示（不报错），监控列表不变

#### Scenario: 仅扫描发现的项目无法被移除
- **WHEN** 一个仅由扫描自动发现的项目被执行 `--remove-project`
- **THEN** 由于它不在配置中，返回未变更提示；其仍会因扫描出现在监控列表
