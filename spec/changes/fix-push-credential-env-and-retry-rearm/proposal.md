# Proposal: fix-push-credential-env-and-retry-rearm

## Why

2026-11-09 cloud-phone 项目推送事故实证了两条推送车道单点故障：daemon 环境缺 `$HOME` 时 git 找不到凭证存储（`could not read Username` / `$HOME not set`），推送凭证只剩 remote URL 内嵌 token 一条腿，token 一吊销（`Authentication failed`）全部推送瘫痪；且 done 态推送失败进入退避后（`_push_backoff_next_retry_at` 已写盘），daemon 内**不存在任何到期重试消费通道**（`event_bus._recover_one` 无 done 分支），重试定时器不跨重启存活，spec 永久滞留 done，只能人工 `/fenix-approve` 救回（当日上午 m0×4、client-ux×1 因无 HOME 全败，gaming-uplink-1080p 因退避无消费者滞留 4 小时）。

## What Changes

- **git 子进程环境确定性**：推送的 git 子进程不再裸继承 daemon 环境——新增单源解析器（HOME 依次取 daemon env → pwd passwd 目录 → 配置覆盖），显式注入 `env=`；提供显式 credential helper 文件路径兜底（`pm.push.credential_file`，默认解析后 HOME 下的 `.git-credentials`），凭证通道从「内嵌 URL 单腿」变「内嵌 URL + 凭证文件双腿」。
- **承载层 HOME 基线**：`capture_env_candidate` 捕获 env 候选稿时对 HOME 做基线检查（缺失则按 PATH 基线同款范式补齐并留痕）；unit 模板内置 `Environment=HOME=<resolved>` 保底行（EnvironmentFile 缺席或无 HOME 键时 daemon 仍带 HOME 启动），迁移摘要增加 HOME 卫生结论。
- **启动凭证自检**：daemon 启动自检链增加推送凭证探测（解析 HOME 是否存在、凭证文件是否在场、remote URL 是否含内嵌凭证），双腿皆缺时发 WARNING 级自检告警（fail-open，不阻断启动）。
- **done 态推送退避续推**：`_recover_one` 增加 done 分支——周期扫描成为退避到期重试的消费通道（不引入内存定时器，对齐 scheduled-reverify-restart-durability 既有纪律）；退避期内跳过、到期拾起重推（复用 approve_push 既有单飞锁/幂等/SHA 去重，经 admin executor 非阻塞投递）；重试次数达 `pm.push.max_retries` 已升级 push_failed 的 spec 不再自动重试（维持 push-ref-hygiene 既有收敛语义）。daemon 重启场景由同一周期扫描天然覆盖。

## Capabilities

### New Capabilities

- `push-credential-environment`: 推送 git 子进程的环境与凭证确定性——HOME 单源解析与显式注入、credential helper 文件兜底、承载层 env 捕获与 unit 模板的 HOME 基线、启动凭证自检告警。
- `push-retry-recovery`: done 态推送失败的退避续推——周期扫描作为退避到期消费通道（跨重启存活）、退避门与重试上限收敛、与既有推送幂等/单飞机制的复用边界。

### Modified Capabilities

（无——`push-ref-hygiene` 的退避级数 [300,900]/max_retries=3/push_failed 升级语义全部保持不变，本 SPEC 只新增其缺失的消费通道；`systemd-env-path-hygiene` 的 PATH 基线行为逐字节不变，HOME 基线为并列新增。）

## Impact

- `core/pm_engine/engine.py`（`_git_push_ref` 注入 env、退避续推复用点）、新文件 `core/git_env.py`（HOME 解析与 git env 单源）、`core/systemd_hosting.py`（HOME 基线捕获与 unit 模板保底行）、`bin/migrate_to_systemd.py`（迁移摘要 HOME 结论）、`fenixd.py`（启动自检凭证探测）、`core/event_bus.py`（`_recover_one` done 分支）。
- 配置新增 `pm.push.credential_file`（可选，缺省不写＝默认凭证文件）；`pm.push.retry_backoff_seconds` / `pm.push.max_retries` 语义不变。
- 行为影响面：所有项目的 done→pushed 自动推送；无 API 破坏，存量项目零迁移（无 HOME 的存量 daemon 由启动自检告警 + unit 保底行自愈）。
