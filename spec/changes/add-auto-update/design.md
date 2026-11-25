## Context

fenixd 框架与 dsh-plugins 的发布链已就绪（双仓 tag `v*` → GitHub Actions → GitHub Release 制品：tar.gz/zip + sha256），但消费面只有「一次性安装」：Agent 按 `docs/install.md` 下载制品解压 + 幂等 installer。已安装实例（框架制品根含打包时写入的 `VERSION` 文件，如 `v0.1.7`）没有任何「发现新版本→获得新功能」的通道，升级等价于人工重走整本手册。

既有可复用资产：GitHub `releases/latest` API 查询先例（install.md §3A/§6b，零新增服务器）、制品 sha256 校验先例、`scripts/package.sh` 制品完整性断言清单、`restart_request` 信号 + supervisor 排水重启、installer 幂等（skills 软链/PATH/用户级配置重跑刷新）、dashboard 运维页（`pages/activities/`）与 API 面（`core/dashboard/server.py`）。约束：不新增发布服务器；dsh-plugins 为私库（Release 资产下载需凭证，workflow 注释与手册口径冲突时按双腿兼容处理）；Windows 下运行中进程对框架目录的 CWD/句柄占用约束换装策略。

## Goals / Non-Goals

**Goals:**

- 已安装（制品路径）用户：自动发现新版本（框架 + dsh-plugins）、dashboard 可见、确认后一键更新、失败可回滚。
- 发布侧零新增基础设施：只消费既有 GitHub Release/Tag。
- 半自动边界：检查自动、应用显式触发；在飞 run 保护；用户级配置与项目骨架零改写。
- 双平台（Linux/Windows）统一换装语义；源码形态优雅降级。

**Non-Goals:**

- 全自动无人值守应用更新（含 beta/prerelease 渠道）——releases/latest 天然 stable-only，本能力不做渠道矩阵。
- 源码形态自动更新（git clone 用户提示 git pull，不做 pull 编排）。
- dsh-plugins 仓库发布流水线改造（VERSION 进包等）——属另一仓库，仅文档建议。
- 跨机器机群式更新、任意历史版本回退（仅保留一代回滚副本）。
- daemon 自身业务逻辑变更（只挂只读周期检查，不碰调度/派发链）。

## Decisions

### D1 版本单源与形态判定

框架本地版本唯一来源 = 制品根 `VERSION`（pack-time `printf '%s\n' "$V" > VERSION`，与 package.sh 既有行为一致）；文件缺失即 source 形态。dsh-plugins 本地版本 = profile 依赖里 link: 目标目录名解析（`dsh-plugins-<tag>`，现状兼容主源），制品根 `VERSION` 存在时优先（为插件仓未来进包留兼容位）。版本比较用手写语义化数值 tuple 比较，不引入第三方依赖（框架 pip 依赖面零膨胀）。替代方案（git describe / 手工配置版本）被否：制品路径用户无 git 元数据，手工配置必然漂移。

### D2 远端查询：releases/latest + 双腿鉴权

`GET https://api.github.com/repos/<owner>/<repo>/releases/latest`（天然排除 draft/prerelease = stable 渠道语义）。fenixd 公开仓匿名直查；dsh-plugins 按匿名先行、HTTP 401/404 回退本机凭证（gh CLI `gh auth token` → git credential helper，只读使用、不持久化 token）双腿处理——手册与 workflow 注释的公开/私库口径分歧由运行时自适应覆盖。单次查询带超时，失败静默留存原因，退避重试，不打告警（匿名限流 60/h，24h 周期 + 手动检查远低于限流面）。

### D3 检查调度：daemon 只读周期任务 + 框架级共享状态

daemon 挂低频周期检查（默认 24h、启动延迟首检），检查是纯只读（本地 VERSION 读 + 远端 API），在 daemon 进程内安全执行。结果持久化到**框架级、换装存续**位置：`~/.fenix/update/status.json`（用户级 `~/.fenix/` 不随框架目录换装迁移，天然跨项目共享）；并发互斥用同目录 lock 文件（O_EXCL + 陈锁清扫，与既有 spec 锁语义同族）。替代（每 daemon 各自检查）被否：N 个项目 N 次重复 API 消耗限流额度。

### D4 应用编排：分离编排进程（核心决策）

更新应用 MUST NOT 由 daemon 或 dashboard 进程内执行——三段式「停 daemon」会杀死编排者自身。设计：**触发方（dashboard API / CLI）spawn 一个平台化分离的短命编排进程**（POSIX setsid/double-fork；Windows DETACHED_PROCESS），编排进程独立完成 下载→校验→staging→停服务→换装→起服务→状态落盘，进度/结果写 `~/.fenix/update/status.json`，UI 轮询读。daemon 在更新场景只承载检查与状态呈现，应用链完全旁路。替代（daemon 内执行 + 自杀前交接）被否：交接协议复杂度与中断面远超分离进程方案。

### D5 换装策略：停-换-起三段式 + 同盘 rename

- staging：解压到框架根同级 `<parent>/fenixd-update-staging-<ts>/`，按 package.sh 既有完整性断言清单（`VERSION`/`schemas/`/`vendor/floorplan/`/dashboard dist/dsh-bundle dist 等）逐项核验。
- 换装：停**全部服务化进程**（同一框架安装上 N 个项目的 daemon unit 逐一经 `core/systemd_hosting.unit_name_for` 解析 + dashboard unit，一并 stop；Linux systemd user unit stop / Windows NSSM stop，服务名经既有 PAL hosting 链解析——dashboard 与各项目 daemon 均自框架根加载代码/持句柄，不停全会在 Windows 下因占用致 rename 确定性失败、Linux 下把日志/静态文件写进被换走的 `.old` 旧 inode）→ 旧根 rename 为 `<parent>/<原名>.old-<ts>`（同盘 rename 原子）→ staging rename 为框架根（保持原路径不变——既有项目 `.fenix/` 骨架内的 fenixd.py/core 链接与 skills 软链全部路径不变即全部有效，这是**不换根路径**的根本理由）→ 按 stop 逆序起全部 unit。未服务化场景跳过停步并在结果注明。
- 回滚：任一步失败 → `.old-<ts>` rename 回原名 → 起 daemon → 状态记失败。回滚副本保留一代，下次成功换装后清理更旧代。
- 在飞 run 预检：换装前读 STATE/运行状态，存在在飞 run 时拒绝执行（半自动确认后仍过此门），提示等待完成。
- 用户级 `~/.fenix/config.yaml` 与项目 `.fenix/` 不在任何写路径上（installer 不重跑——软链路径不变使其无需刷新；版本门场景按既有 `allow-version` 文档指引）。

被否方案：原地 tar 覆盖（中断=半新半旧混合态，且 Windows 被占用文件 PermissionError 面大）；换新根路径 + 重跑 installer 刷新全部链接（存量项目骨架链接全断，迁移面不可控）。

### D6 dsh-plugins 应用：新目录 + 逐 profile 重注册

下载 zip（同 D2 双腿鉴权）→ sha256 校验 → 解压到旧插件目录**同级**新版本目录 → 枚举 `~/.dsh/profiles/` 下 CLI 可管理 profile（排除 `desktop`——Electron 专属管理，`dsh plugin` 对其硬性拒绝，install.md §6a 已证）→ 对每个 profile 中 link: 指向旧插件目录的 fenix 插件，`dsh plugin --profile <P> remove` + `add link:<新目录>/<插件名>` 确定性重指向（add 覆盖语义不做假设，remove+add 保确定性）→ 逐插件核验 `exports` 指向文件存在。非 fenix 插件（link: 不指向旧插件目录者，如 loopback-trust）不碰。**边界**：link: 目标位于框架根内的插件（如 `link:<框架根>/dsh-bundle`，源码/工作树形态安装的实例）不参与独立插件更新——其内容随框架换装一并就位，检出并在结果注明；插件新目录解压目标 MUST NOT 落在框架根内（否则污染框架根、且下次换装被 `.old` 携走成孤儿）。desktop profile 检出即降级为结果中的文档指引。plugin 注册属进程外 CLI 调用，无 daemon 生命周期纠缠。

### D7 dashboard 面：运维页更新卡 + 三个 API

运维页（`pages/activities/`）新增更新状态卡（或独立页签，实现期按信息密度定）：当前版本/远端版本/检查时刻/形态标识/动作按钮/进度与终态。API 挂 `core/dashboard/server.py` 既有路由面：`GET /api/update/status`（读 `~/.fenix/update/status.json`）、`POST /api/update/check`（同步单次检查）、`POST /api/update/apply`（spawn 分离编排进程，进行中 409）。CLI 面 `bin/fenix_update.py check|apply|status` 与 dashboard 共用同一引擎（无 dashboard 的 CLI-only 部署可用）。

### D8 配置面：用户级 update: 段

`~/.fenix/config.yaml` 新增 `update.enabled`（默认 true）/`update.interval_hours`（默认 24）/`update.mirror`（可空镜像前缀，仅替换制品下载 URL 前缀，sha256 校验口径不变）。模板 `config.user.template.yaml` 只加注释文档不固化默认值（既有纪律）；关闭 enabled 只停周期检查，手动检查入口保留。

### D9 审计留痕

`~/.fenix/update/audits.jsonl` 追加每次检查/应用记录（触发来源、目标版本、阶段序列、结果、失败原因、耗时），运维页读侧展示最近记录；按既有产物保留策略周期清理。归因排障需要「为什么没更新成功」的一手证据。

## Risks / Trade-offs

- [GitHub 匿名限流 60/h] → 24h 周期 + 失败退避 + 手动检查即时反馈；检查失败永不告警轰炸。
- [Windows 换装期目录占用（CWD/句柄/杀毒锁）] → 先停服务再 rename；rename 失败即走回滚路径；staging 与旧根同盘保证 rename 原子性。
- [更新中断留下半换装态] → 三段式每步落盘状态；重启后编排幂等恢复（检测 staging/.old 残留并按状态续走或回滚）。
- [新版框架与已装 dsh 版本门冲突（peerDependencies）] → 更新结果透出 bundle 挂载失败提示，指引既有 `allow-version --accept-risk` 路径（install.md §6c），不做自动放行。
- [dsh-plugins 私库无凭证环境] → 检查结果记失败原因（可区分 401/404 vs 网络失败），docs/help 写明凭证前置；框架更新不受影响（公开仓）。
- [`dsh plugin add` 覆盖语义随 dsh 版本漂移] → remove+add 确定性重注册；重注册后逐插件 exports 验证兜底。
- [dashboard 进程本身跑旧代码] → 换装后内存代码仍自洽；结果中提示刷新/重启 dashboard 以加载新前端 dist（文档 + 更新结果文案）。
- [多项目 daemon 各自触发更新的并发竞态] → 框架级 apply 锁（`~/.fenix/update/apply.lock`）互斥，第二个触发者 409。

## Migration Plan

1. 本 SPEC 实现合入主干后，下一次打 tag（v0.1.8+）发布的制品即天然携带更新引擎——存量 v0.1.7 用户无感（引擎不存在时无任何行为变化）。
2. 存量用户升级路径首跳：手动按 install.md 更新一次至携带引擎的版本，此后进入自动更新闭环。
3. `docs/install.md` 新增「更新」章节（含 CLI 用法、desktop profile 手动半步、版本门放行指引）；`docs/help/` 新增排障 runbook。
4. 回滚策略：单代回滚副本 + 审计留痕；发布缺陷场景下用户可被指引手动 rename 回 `.old` 代并重启 daemon（runbook 覆盖）。

## Open Questions

- 更新卡落在运维页独立页签还是既有页签内嵌卡片——实现期按运维页信息密度与既有页签布局定（spec 已按「运维页展示」约束，形态自由度留给实现）。
- dsh-plugins 制品根未来补 `VERSION` 文件后（插件仓独立改造），本引擎无需变更（D1 已兼容优先读 VERSION）——插件仓改造时点不在本 SPEC 控制内。
