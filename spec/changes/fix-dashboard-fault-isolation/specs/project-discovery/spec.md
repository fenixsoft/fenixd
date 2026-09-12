## MODIFIED Requirements

### Requirement: 默认自动扫描发现 Fenixd 项目

`Registry.discover()` MUST 以自动扫描为主发现被监控项目：当 `~/.config/fenixd/dashboard.yaml` 未配置 `scan_dirs`（或为空）时，MUST 默认将用户主目录（`~`）作为唯一扫描根，遍历其一级子目录，仅当子目录下存在 `.fenix/STATE.md` 才将其识别为 Fenixd 项目并纳入监控列表。显式配置 `scan_dirs` 时 MUST 沿用该配置作为扫描根（覆盖默认）。显式 `projects` 中的项目 MUST 始终出现在监控列表（即使扫描未命中或目录不存在，标记 `exists=False`）。扫描结果与显式注册按规范化路径去重。

扫描 MUST NOT 因单个子目录的失败而整体中断。对每个子目录的类型判断（`is_dir()`）与 `.fenix/STATE.md` 存在性探测（`is_file()`）MUST 被异常隔离：捕获 `OSError` 后跳过该子目录（不计入监控列表、不改动显式 `projects`），并继续处理其余子目录，最终 MUST 正常返回发现结果而非抛异常。注意 `pathlib` 的存在性探测只吞 `ENOENT`/`ENOTDIR`/`EBADF`/`ELOOP`（Python 3.10 `_IGNORED_ERROS = (2, 20, 9, 40)`），**`EIO` 会直接上抛**，因此隔离不得依赖 `is_file()` 的默认吞异常行为。扫描根自身不可读（`iterdir()` 抛 `OSError`）时 MUST 跳过该扫描根并继续处理其余扫描根。

#### Scenario: 默认扫描主目录发现多个项目
- **WHEN** `dashboard.yaml` 未配置 `scan_dirs`，且主目录一级子目录 `~/projectA`、`~/projectB` 各含 `.fenix/STATE.md`
- **THEN** 监控列表同时包含 `projectA` 与 `projectB`，并标记为自动发现（`discovered=true`）

#### Scenario: 非 Fenixd 目录被排除
- **WHEN** 主目录一级子目录 `~/not-a-project` 不含 `.fenix/STATE.md`，且其存在性探测正常返回「不存在」
- **THEN** 该目录不进入监控列表，且不影响其它子目录的发现结果

#### Scenario: 显式注册与扫描结果去重
- **WHEN** `projects` 显式注册了 `~/projectA`，且默认扫描也发现 `~/projectA`
- **THEN** 监控列表中 `projectA` 只出现一次

#### Scenario: 不可读子目录被跳过而不中断发现
- **WHEN** 主目录一级子目录中存在一个目录，对其 `.fenix/STATE.md` 的存在性探测抛出 `OSError`（errno `EIO`），同时主目录下另有满足条件的 Fenixd 项目
- **THEN** `discover()` 不抛异常，正常返回；该不可读目录不出现在监控列表中；满足条件的 Fenixd 项目 MUST 仍出现在监控列表中

#### Scenario: 不可读子目录不影响显式注册项目
- **WHEN** 扫描根下存在探测抛 `OSError` 的目录，且 `dashboard.yaml` 显式注册了 `~/fenixd`
- **THEN** `discover()` 正常返回，`~/fenixd` MUST 出现在监控列表且 `discovered=false`

#### Scenario: 扫描根整体不可读时跳过该根
- **WHEN** 某个 `scan_dirs` 条目的 `iterdir()` 抛出 `OSError`
- **THEN** 该扫描根被跳过，其余扫描根与显式 `projects` 的结果 MUST 正常返回

#### Scenario: 目录类型判断抛异常同样被隔离
- **WHEN** 对某个子目录的 `is_dir()` 调用抛出 `OSError`（含 `EIO`）
- **THEN** 该子目录被跳过，发现流程继续，`discover()` 正常返回

## ADDED Requirements

### Requirement: 忽略列表在目录可读性探测之前生效

`Registry.discover()` MUST 在扫描阶段对候选子目录**先**执行 `ignored` 过滤、**再**执行目录类型判断与 `.fenix/STATE.md` 存在性探测。当某路径同时位于 `ignored` 列表中时，MUST NOT 对该路径执行任何可能抛出 `OSError` 的文件系统探测。

本要求的动机：软删除（写入 `ignored`）是用户面对不可读/故障目录时的逃生通道；若过滤发生在探测之后，探测抛出的异常会先于过滤发生，导致「把坏目录加入忽略列表」这一操作在生效前就已被异常吞掉，逃生通道失效。

`ignored` 的路径匹配 MUST 基于规范化路径（与写入侧 `_norm` 使用同一规范化方式），且对**尚不可读**的路径 MUST 能完成匹配与过滤。`Registry.add_ignored(path)` MUST NOT 因目标路径不可读而拒绝写入。

#### Scenario: 不可读目录加入忽略列表后不再触发探测
- **WHEN** 某子目录的 `.fenix/STATE.md` 探测会抛 `OSError`，用户将该子目录路径写入 `ignored`
- **THEN** `discover()` 正常返回，且不因该子目录产生异常或日志中的探测失败

#### Scenario: 不可读路径可被写入忽略列表
- **WHEN** 对路径解析后位于扫描根下、但目录本身不可读的路径调用 `Registry.add_ignored(path)`
- **THEN** 该规范化路径被写入 `dashboard.yaml` 的 `ignored` 列表，返回成功

#### Scenario: 忽略过滤先于探测
- **WHEN** 对同一子目录，既命中 `ignored` 又会在探测时抛 `OSError`
- **THEN** 该子目录被忽略过滤短路，探测函数 MUST NOT 被调用（以 mock 断言调用次数为 0 的方式可验证）

### Requirement: 扫描跳过不可读目录的可观测性

发现层跳过不可读子目录时 MUST 输出一条 WARNING 级日志，内容 MUST 至少包含被跳过的路径与错误原因（errno 或异常摘要），以便在磁盘故障等场景下定位「哪个目录被漏掉了」。该日志 MUST NOT 使请求失败，UI 层对本情形静默（不生成项目卡片、不追加告警条目）。

#### Scenario: 跳过不可读目录时写入 WARNING 日志
- **WHEN** 扫描过程中某子目录的探测抛出 `OSError`
- **THEN** 日志中出现一条 WARNING 记录，包含该子目录路径与错误原因，且 `discover()` 的返回值不受影响

#### Scenario: 跳过不产生 UI 可见条目
- **WHEN** 某子目录被跳过
- **THEN** `/api/projects` 与 `/api/overview` 的返回中 MUST NOT 出现该路径对应的项目卡片或告警条目
