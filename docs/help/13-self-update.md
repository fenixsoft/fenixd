# 自动更新排障 runbook

框架与 dsh-plugins 自动更新（add-auto-update）的排障手册：状态字段解读、常见失败
原因与处置、私库凭证前置、更新中断后半换装态的人工恢复。工作方式与 CLI 用法见
安装手册 §12（[docs/install.md](../install.md) §12）；配置键见
[配置参考](09-config.md) 的 `update` 段。

## 状态与审计文件位置

全部框架级、跨项目共享（`~/.fenix/` 不随框架目录换装迁移）：

| 文件 | 内容 |
|------|------|
| `~/.fenix/update/status.json` | 更新状态单源：框架/插件本地与远端版本、检查时刻、失败原因、应用编排阶段 |
| `~/.fenix/update/audits.jsonl` | 审计留痕：每次检查/应用一行（触发来源、目标版本、阶段序列、结果与原因、耗时） |
| `~/.fenix/update/check.lock` / `apply.lock` | 检查与应用互斥占位锁（陈锁自动清扫：check 15 分钟、apply 2 小时） |
| `<框架根同级>/fenixd.old-<时间戳>` | 换装回滚副本（仅保留一代） |
| `<框架根同级>/fenixd-update-staging-<时间戳>` | 换装 staging（成功/失败后自动清理；残留见下文幂等恢复） |

`status.json` 字段速查（`bin/fenix_update.py status --json` 可直接输出）：

- `framework` / `plugins`：各自 `local_version`（本地）、`remote_version`（远端 latest）、
  `form`（`artifact`=制品形态 / `source`=源码形态 / `unknown`）、`update_available`
  （可更新判定；语义化数值比较，`v0.1.10 > v0.1.7`）；
- `last_check_at` / `last_success_at`：最近一次尝试 / 最近一次全部成功的时刻（UTC）；
- `last_error`：最近失败原因（成功时为 null）；
- `failure_count` / `next_check_after`：连续失败计数与退避到期时刻——**退避窗内手动
  检查不受限**，仅 daemon 周期检查被推迟；
- `apply`：应用编排段——`phase`（`queued` 受理 / `running` 执行中 / `success` /
  `failed`）、`stages`（阶段序列：下载→校验→staging→stop→swap→start→cleanup）、
  `failed_stage` + `error`（失败定位）、`rollback`（是否已回滚）。

## 常见失败原因与处置

### 检查失败：GitHub API 限流（403）

`last_error` 形如「GitHub API 限流或拒绝（匿名 60/h 上限）」。匿名配额 60 次/小时；
周期检查（24h）+ 手动检查远低于此面，连续触发通常是脚本高频轮询或出口 IP 共享配额。

**处置**：等下一个小时窗（配额按整点刷新）；或配置 `update.mirror` 走镜像（仅替换制品
下载前缀，API 域名不走镜像——限流属 API 面，镜像不缓解检查限流）。检查失败不影响
已安装框架的任何行为。

### 检查失败：私库无凭证（401/404）

fenixd 为公开仓匿名直查；dsh-plugins 按匿名先行、401/404 回退本机凭证。双腿全败时
`last_error` 形如「需要凭证（私库且双腿鉴权未取得可用 token）」。

**私库凭证前置配置**（二选一，只读使用、引擎不落盘 token）：

```bash
# 腿一：gh CLI 登录态
gh auth login            # 或 gh auth token 能输出非空 token 即可
# 腿二：git credential helper（store 形态示例）
git config --global credential.helper store
git credential approve <<'EOT'
protocol=https
host=github.com
username=<your-user>
password=<your-token>
EOT
```

注意：配置 `update.mirror` **不**改变 API 查询域（仍查 api.github.com）——私库检查
必须有凭证，镜像只加速制品下载。

### 应用失败：在飞 run 拒绝（preflight）

`apply.phase=failed`、`failed_stage=preflight`、错误含「存在在飞 run」。换装前预检
各项目 `.fenix/runs/*.jsonl` 非归档记录（6 小时内有写入判在飞），保护在飞 run 不被
停机打断。

**处置**：等在飞 run 完成后重试一键更新。长期不消的记录（daemon 崩溃残留）超 6 小时
自动不再判在飞；确认无 run 在跑时也可直接重试。

### 应用失败：Windows 目录占用（stop/swap 阶段）

`failed_stage=stop` 或 `swap`、错误含「占用未排净」。运行中进程对框架目录的 CWD/
句柄占用会让 rename 确定性失败。

**处置**：确认全部服务化进程已被停（`sc query` 各 NSSM 服务态）；手工关闭占用框架
目录的终端/编辑器后重试。失败时本地安装零改动（stop 失败）或已自动回滚（swap 失败），
不会留下半新半旧混合态。

### 应用失败：sha256 校验 / 完整性断言（verify / staging 阶段）

下载制品校验不过或 staging 缺件（清单逐字对齐 package.sh）。本地安装**零改动**，直接
重试即可；反复失败多为镜像同步滞后（配置了 `update.mirror` 时镜像侧制品未跟上 Release），
可临时清空 `update.mirror` 直连下载。

### 应用失败：download 阶段（读停滞/连接重置）

制品下载自动重试 2 次（共 3 次尝试，每次全新连接，间隔 2s/5s）后仍失败才报
`download` 阶段失败，本地安装零改动。仍失败时：直接重试（失败多为长连接中途
停滞，换连接常可通过）；或在 `~/.fenix/config.yaml` 配 `update.mirror` 走镜像；
环境变量 `HTTPS_PROXY`/`HTTP_PROXY` 对下载生效（urllib 默认读环境代理）。
历史版本（≤v0.2.0）此类失败曾误报为 `unexpected` 阶段，v0.2.1 起归位 `download`。

### 应用失败：CLI 触发的编排进程秒退（Windows，≤v0.2.2 已治本）

Windows 上用 CLI（`python3 bin/fenix_update.py apply …`）触发更新，编排进程
spawn 后立即消失、无任何日志，而状态文件偶见 `already running`/`running` 残留。
根因（2026-11-28 客户端实证）：Windows 触发方为编排进程挂 KILL_ON_JOB_CLOSE
的 Job 对象（daemon 死亡联动子树自杀的守护语义），瞬时触发方（CLI 受理即退）
退出时句柄表销毁，Job 联动把**编排进程自己**秒杀——守护语义误伤了一次性触发
形态。v0.2.3 起治本：spawn 时把 Job 句柄移交编排进程自持（`keep_job_after_parent`），
触发方退出不再联动。旧版本规避：改用 dashboard 设置页「一键更新」（网页触发，
dashboard 服务长存不触发联动）。

Windows CLI 触发排障速查：

| 现场 | 含义 | 处置 |
|------|------|------|
| CLI 触发后编排进程立即消失、零日志 | Job 联动误伤编排进程（≤v0.2.2） | 升级 ≥v0.2.3；旧版改用 dashboard 网页触发 |
| `status.json` 卡 `running` / 报 `already running` 但无编排进程 | 上一编排进程被秒杀，状态未收尾 | 等锁陈旧超时后重试，或手工清 `~/.fenix/update/apply.lock` |
| 换装成功但新增 skill / 命令不出现 | skill 注册面不随制品更新自动执行 | 重跑安装器（幂等，只补注册不动数据）后生效 |

### 镜像健康探测（check 阶段告警，v0.2.3 起）

配置了 `update.mirror` 时，每次检查（手动或周期）会对镜像形态的制品 URL 做
1 字节 Range 探测（10s 超时）：探测失败**不阻断检查**、不改变可用性判定，只在
状态里记 `mirror_warning`（`python3 bin/fenix_update.py status` 或 dashboard
更新页 API 可见），提示「镜像源可能停服或路径不可用」——此时应用多半会在镜像
通道失败后自动回退直连，告警只是把故障面提前到检查阶段暴露。镜像为空（官方
直连）时不探测，遗留告警自动清除。

### 配置 update.mirror 走大陆镜像（实测口径，2026-11-28）

**最简路径：dashboard 设置 → 自动更新 →「下载源」**，在 官方站点 /
镜像加速（ghfast.top）/ 备用镜像（ghproxy.net）间点选即写本配置（对下一次
「一键更新」即时生效，无需重启）；非 https 的镜像域名或带尾巴的自定义值选
「自定义」填入。以下为手工配置同一键的口径。

**缺省即镜像**（2026-11-28 起）：`update.mirror` 键缺失时下载通道默认走
镜像（镜像失败自动回退官方直连）；选「GitHub official」会显式持久化
`mirror: ""`（空串键=官方直连，与键缺失可区分）。下载走双通道候选：
配置镜像在前、直连兜底，每通道独立享受 3 次连接重试，另设 600s 墙钟
硬上限与 Content-Length 尺寸断言（干净截断不等 sha256 即重试）。

gh-proxy 形态镜像要求「完整原 URL 跟在域名后」，`update.mirror` 值**带上
`/https://github.com` 尾巴**即可兼容（mirror 只做前缀替换，尾巴原样保留）：

```yaml
update:
  mirror: https://ghfast.top/https://github.com
```

实测（13.5MB 制品 fenixd-v0.2.1.tar.gz，家庭宽带直连口径）：

| 镜像 | 配置值 | 结果 |
|----|----|----|
| ghfast.top | `https://ghfast.top/https://github.com` | **15.4s 下载完成（约 0.9MB/s），sha256 校验通过**——推荐 |
| ghproxy.net | `https://ghproxy.net/https://github.com` | 小文件 7.4s 正常；大文件 180s 仅 5.3MB（约 30KB/s）——仅作备用 |
| ghproxy.homeboyc.cn / github.akams.cn / gh.llkk.cc / kkgithub.com / bgithub.xyz | — | 403 / 404 / 超时，不可用 |

注意三点：镜像只加速制品下载，API 检查（api.github.com）仍直连；镜像站属社区
公益服务，随时可能停服（gh-proxy.com 已于 2026-10-13 停服），失效时在设置页
改选「GitHub official」（或把 `update.mirror` 设为空串）即回直连——注意键
缺失与空串语义不同（键缺失=缺省镜像）；镜像同时伺服制品与 sha256 文件
（校验同源），对镜像本身不构成完整性防篡改——对供应链有要求时优先自建代理
或走可信出口。

## 更新中断后半换装态的人工恢复

编排每步落盘，重启后编排进程会**幂等恢复**（接管可用 staging、回滚根缺失态）。仅当
幂等恢复自身失败（错误含「须人工恢复」）时按下面手工处理。先看现场：

```bash
ls <框架根同级>/            # 确认三形态：框架根在不在、.old-* 、staging-*、.update-failed-*
cat ~/.fenix/update/status.json   # apply.failed_stage 与 rollback 字段
```

| 现场 | 含义 | 处置 |
|------|------|------|
| 框架根在、`.old-*` 在、phase=failed(rollback_restored=true) | 回滚已完成 | 无需动作；`.old-*` 留待下次成功换装清理 |
| 框架根**缺失**、`.old-<ts>` 在 | 换装②后③前中断且恢复失败 | `mv <parent>/fenixd.old-<ts> <框架根>`，再拉起服务 |
| 框架根在（新版本）、`.old-<ts>` 在、phase=failed(start) | 换装完成但服务未恢复 | 按回滚或接受新版二选一：接受→手工拉起服务并删 `.old-*` 之外的多余代；回退→见安装手册 §12.6 |
| `fenixd-update-staging-*` 残留 | 下载/断言阶段中断 | 完整（含全部清单文件）会被下次编排自动接管；否则直接删除 |

人工恢复后跑 `python3 bin/fenix_update.py status` 确认 `apply` 段与本地 `VERSION` 一致，
再重新触发一次检查即可回到正常循环。

## 相关文档

- [安装手册 §12 更新与版本演进](../install.md) — 工作方式、CLI、版本门、desktop 半步、回滚
- [配置参考 update 段](09-config.md#update自动更新add-auto-update) — 三键配置
- [日志体系](11-logs.md) — daemon 日志与结构化事件（编排异常的服务端留痕）
