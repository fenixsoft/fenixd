# auto-update Specification

## ADDED Requirements

### Requirement: 本地版本单源与安装形态判定

更新引擎 SHALL 以框架制品根的 `VERSION` 文件（打包时写入 Release tag 名，如 `v0.1.7`）为 fenixd 框架本地版本的唯一来源；`VERSION` 文件缺失或不可读时 SHALL 判定为 source 形态（源码安装）。dsh-plugins 本地版本 SHALL 从 dsh profile 依赖清单中 link: 指向的插件目录名解析（`dsh-plugins-<tag>` 形态）为现状兼容主源；制品根存在 `VERSION` 文件时以其为优先。版本比较 SHALL 按语义化版本数值逐段比较（v0.1.10 > v0.1.7），禁止字符串字典序。

#### Scenario: 制品形态读版本

- **WHEN** 框架制品根存在 `VERSION` 文件且内容为 `v0.1.7`
- **THEN** 本地版本判定为 `v0.1.7`、安装形态判定为 artifact

#### Scenario: 源码形态判定

- **WHEN** 框架根不存在 `VERSION` 文件（git clone 源码目录）
- **THEN** 安装形态判定为 source，后续检查与应用按源码降级语义处理

#### Scenario: 插件版本从目录名解析

- **WHEN** 某 profile 依赖中 fenix 插件的 link: 目标目录名为 `dsh-plugins-v0.1.2`
- **THEN** 该 profile 的 dsh-plugins 本地版本解析为 `v0.1.2`

#### Scenario: 语义化版本比较

- **WHEN** 本地版本 `v0.1.7` 与远端版本 `v0.1.10` 比较
- **THEN** 判定远端更新可用（数值比较 10 > 7，而非字典序 "10" < "7"）

### Requirement: 远端最新版本查询

更新引擎 SHALL 查询 GitHub `releases/latest` API 获取远端最新稳定版 tag（该接口天然排除 draft 与 prerelease），fenixd 查询 `fenixsoft/fenixd`，dsh-plugins 查询 `fenixsoft/dsh-plugins`。fenixd 为公开仓库 SHALL 匿名直查；dsh-plugins 按「匿名先行，HTTP 401/404 时回退本机凭证」双腿处理（凭证取 gh CLI 登录态或 git credential helper，不新增配置项）。查询 SHALL 携带超时与单次尝试上限，网络失败/限流不重试轰炸。

#### Scenario: 公开仓库匿名查询

- **WHEN** 查询 fenixd 最新 Release 且网络可达
- **THEN** 无需任何凭证返回 `tag_name` 与制品下载 URL

#### Scenario: 私库双腿回退

- **WHEN** dsh-plugins 匿名查询返回 401 或 404 且本机存在 gh CLI 登录凭证
- **THEN** 以该凭证重试查询并成功返回结果

#### Scenario: 双腿全败静默

- **WHEN** 匿名与凭证查询均失败（网络不可达/无限流凭证/限流）
- **THEN** 本次检查记为失败并留存原因，不产生告警、不重试轰炸

#### Scenario: prerelease 不进入 stable 检查

- **WHEN** 仓库最新发布为 prerelease（`releases/latest` 不返回它）
- **THEN** 检查结果以最近一个正式 Release 为准，prerelease 不触发可更新判定

### Requirement: 周期检查调度

daemon SHALL 挂载低频周期检查任务：默认每 24 小时一次、daemon 启动后延迟首检（避免启动风暴），间隔可配。检查结果（本地版本/远端版本/检查时刻/可更新判定/失败原因）SHALL 持久化为框架级状态文件，同一机器多项目 daemon 读到同一份状态；并发检查 SHALL 以框架级互斥防重（首个检查者执行，其余直接读现有状态）。

#### Scenario: 周期到点自动检查

- **WHEN** 距上次成功检查已超过配置间隔且更新检查开关开启
- **THEN** daemon 触发一次检查并刷新框架级更新状态文件

#### Scenario: 检查失败退避静默

- **WHEN** 检查因网络失败未取得远端版本
- **THEN** 状态文件保留上次成功结果并附最近失败原因与时刻，按退避间隔重试，不重复告警

#### Scenario: 多 daemon 幂等共享

- **WHEN** 同一框架安装上的第二个项目 daemon 到达检查时点而框架级互斥已被占用
- **THEN** 它不重复发起检查，直接读共享状态文件呈现

### Requirement: 更新状态展示与一键更新入口

dashboard 运维页 SHALL 展示更新状态卡：当前版本、远端最新版本、最近检查时刻、可更新判定与安装形态标识（artifact / source）。artifact 形态 SHALL 提供「立即检查」与「一键更新」动作；一键更新 MUST 经用户确认后执行（半自动边界：检查自动、应用显式触发）。source 形态 SHALL 显示「git pull 更新」指引而非更新按钮。更新执行期间 SHALL 展示阶段进度（下载/校验/换装/重启）与终态（成功/失败及原因）。

#### Scenario: 可更新状态呈现

- **WHEN** 检查判定存在更新（本地 v0.1.7、远端 v0.1.8）
- **THEN** 运维页更新卡显示两版本与「一键更新」按钮

#### Scenario: 已是最新态

- **WHEN** 本地版本等于远端最新版本
- **THEN** 更新卡显示「已是最新」且不提供更新动作

#### Scenario: 源码形态指引

- **WHEN** 安装形态为 source
- **THEN** 更新卡显示源码形态标识与「git pull 更新」指引文案，不出现一键更新按钮

#### Scenario: 更新进度可见

- **WHEN** 一键更新执行中
- **THEN** 更新卡按阶段刷新进度，完成后显示成功或失败原因

### Requirement: 框架更新应用（三段式换装）

artifact 形态的一键更新 SHALL 执行：① 下载目标版本制品（tar.gz/zip）与 `.sha256` 并强校验，失败即中止；② 解压至框架同级 staging 目录并按制品完整性清单断言硬读面在位（`VERSION`、`schemas/`、`vendor/floorplan/`、dashboard dist、dsh-bundle dist 等）；③ 双平台统一「停 daemon → 原子换装 → 起 daemon」——换装前预检在飞 run，存在在飞 run 时 MUST 拒绝执行并提示等待；换装保留旧目录一代作为回滚副本；起 daemon 经既有 restart 语义恢复。用户级配置（`~/.fenix/config.yaml`）与项目 `.fenix/` 骨架 MUST NOT 被更新动作改写。

#### Scenario: 制品下载校验失败中止

- **WHEN** 下载的制品 sha256 与 `.sha256` 不匹配
- **THEN** 更新中止并报失败原因，本地安装不受任何改动

#### Scenario: staging 完整性断言拦截

- **WHEN** staging 解压后完整性清单存在缺件（如 `schemas/spec-driven/schema.yaml` 缺失）
- **THEN** 更新中止并报缺失项，本地安装不受任何改动

#### Scenario: 在飞 run 预检拒绝

- **WHEN** 用户触发一键更新时存在在飞 run
- **THEN** 更新拒绝执行并提示等待在飞 run 完成后重试

#### Scenario: 三段式换装成功

- **WHEN** 无在飞 run、制品校验与完整性断言通过
- **THEN** 停 daemon → 旧目录保留为回滚副本 → staging 就位为框架根 → 起 daemon，更新后 `VERSION` 读回为目标 tag

#### Scenario: 用户配置与项目骨架保留

- **WHEN** 框架换装完成
- **THEN** `~/.fenix/config.yaml` 内容不变，既有项目 `.fenix/` 骨架（含其指向框架根的链接）继续有效可用

### Requirement: 框架更新失败回滚

换装任何一步失败时 SHALL 回滚：回滚副本恢复为框架根、daemon 按原版本重启、更新状态记为失败并留存失败阶段与原因；回滚副本保留一代，下次成功换装后清理上一代。

#### Scenario: 换装中断回滚

- **WHEN** 换装步骤（目录就位）执行失败
- **THEN** 回滚副本恢复为框架根、daemon 以原版本恢复运行，更新状态标记失败并含失败阶段

#### Scenario: 回滚副本代际清理

- **WHEN** 一次更新成功完成后又发生下一次成功更新
- **THEN** 仅保留最近一代回滚副本，更旧一代被清理

### Requirement: dsh-plugins 更新应用

一键更新 SHALL 同时更新 dsh-plugins：下载目标版本插件制品 zip 并 sha256 校验 → 解压为新版本目录 → 对本机各 CLI 可管理 dsh profile 中 link: 指向旧插件目录的 fenix 插件逐一重新注册指向新目录（保留 loopback-trust 等非 fenix 插件不动）→ 逐插件验证其 `exports` 指向文件存在。desktop profile（Electron 专属管理）MUST NOT 被自动改写——检出时降级为文档指引提示。插件目录更新后框架根目录名无关性不受影响。

#### Scenario: 插件重注册成功

- **WHEN** profile `fenix` 的依赖含 10 个 link: 指向 `dsh-plugins-v0.1.2` 的 fenix 插件且新版 v0.1.3 解压完成
- **THEN** 10 个插件的 link: 全部重注册指向 `dsh-plugins-v0.1.3`，各插件 `exports` 指向文件存在

#### Scenario: 非 fenix 插件保持不动

- **WHEN** profile 中还存在 link: 指向其他目录的插件（如 loopback-trust）
- **THEN** 该类插件依赖不被改写

#### Scenario: desktop profile 降级指引

- **WHEN** 检测到 desktop profile 存在指向旧插件目录的 fenix 插件
- **THEN** 不自动改写该 profile，更新结果中给出桌面版手动更新文档指引

### Requirement: 更新配置面

用户级配置 SHALL 新增 `update:` 段：`enabled`（检查开关，默认开）、`interval_hours`（检查间隔，默认 24）、`mirror`（制品下载镜像前缀，可空）。配置变更对下一次检查生效；关闭开关后 daemon 不再自动检查，但 dashboard 手动「立即检查」仍可用。

#### Scenario: 关闭自动检查

- **WHEN** 用户配置 `update.enabled: false`
- **THEN** daemon 周期检查不再触发，dashboard 手动检查入口仍可用

#### Scenario: 自定义镜像下载

- **WHEN** 用户配置了 `update.mirror` 前缀且触发更新下载
- **THEN** 制品下载 URL 走镜像前缀，sha256 校验口径不变

### Requirement: 更新过程审计留痕

每次检查与更新动作 SHALL 留存审计记录（触发来源、目标版本、阶段序列、结果与失败原因、耗时），供运维页读侧展示与排障回溯；审计记录按既有产物保留策略清理。

#### Scenario: 更新审计可回溯

- **WHEN** 一次更新完成（无论成败）
- **THEN** 可查到该次更新的触发来源、阶段序列与结果原因

#### Scenario: 检查审计轻量留存

- **WHEN** 周期检查完成
- **THEN** 检查结果与时刻可查，不产生告警噪音
