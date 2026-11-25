# 框架与插件自动更新

<!-- knowledge: capability=auto-update rev=1
     sources=spec/changes/add-auto-update -->

fenixd 框架与 dsh-plugins 的自更新闭环：daemon 周期发现新版本、运维页呈现更新状态、用户确认后一键换装（框架三段式换装 + 插件重注册）、失败回滚、源码形态优雅降级。发布侧零新增基础设施，只消费既有 GitHub Release/Tag 制品。

## 规则

- **版本单源与形态判定**：框架本地版本唯一来源是制品根 `VERSION` 文件（打包时写入 Release tag 名，如 `v0.1.7`）；文件缺失或不可读即判定 source 形态（源码安装）。dsh-plugins 本地版本以制品根 `VERSION` 为优先，缺省时从 dsh profile 依赖中 link: 指向的插件目录名解析（`dsh-plugins-<tag>` 形态）。版本比较按语义化版本数值逐段比较（`v0.1.10 > v0.1.7`），禁止字符串字典序。
- **远端查询**：以 GitHub `releases/latest` API 获取远端最新稳定版 tag（该接口天然排除 draft 与 prerelease，即 stable-only 渠道语义）。fenixd 公开仓匿名直查；dsh-plugins 按「匿名先行，HTTP 401/404 回退本机凭证」双腿处理（凭证先取 gh CLI 登录态、再 git credential helper；只读使用、不落盘 token、不新增配置项）。查询携带超时与单次尝试上限。
- **检查纯只读、失败静默**：检查只做本地 VERSION 读 + 远端 API 查询，在 daemon 进程内安全执行；source 形态框架段免远端查询。网络失败/限流静默留存原因（status.json 的 `last_error`），按指数退避重试（1h/2h/4h… 封顶 interval_hours），不产生告警、不重试轰炸。
- **周期调度挂 daemon 主循环 tick**：daemon 每 tick 调用检查入口，按 `update.interval_hours`（默认 24）与 status.json 上次检查时刻判到期，启动延迟首检避免启动风暴；检查异常自吞记日志，不中断 daemon 主循环。`update.enabled: false` 只停周期检查，dashboard 手动「立即检查」仍可用。
- **框架级共享状态**：检查结果持久化到 `~/.fenix/update/status.json`（原子写），同一机器多项目 daemon 读到同一份；并发检查以 `check.lock` 互斥（O_EXCL + 陈锁清扫），第二个到达者不重复发起、直接读现态；应用互斥用 `apply.lock`（陈锁兜底 2 小时），并发触发的第二触发者得到 409。
- **运维页更新卡**：运维页「更新」页签展示框架/插件各自的当前版本、远端版本、最近检查时刻、可更新判定与安装形态标识（artifact/source）。artifact 形态提供「立即检查」「一键更新」；一键更新必须经用户确认（半自动边界：检查自动、应用显式触发）；source 形态显示「git pull 更新」指引文案、不渲染更新按钮。执行期间按阶段刷新进度（下载/校验/换装/重启），终态呈现成功或失败原因。
- **更新 API 契约**：`GET /api/update/status`（读 status.json，缺文件返回 never-checked 兜底形态，引擎持久载荷无 checked 键）；`POST /api/update/check`（同步单次检查，检查失败是业务结果而非 HTTP 错误——恒 200 + ok/status 字段）；`POST /api/update/apply`（进行中/锁占用返回 409，否则 spawn 分离编排返回受理）。CLI `bin/fenix_update.py check|apply|status` 与 dashboard 共用同一引擎，退出码区分成功（0）/无更新（1）/失败（2）；source 形态 apply 直接拒绝（退出码 2）并提示 git pull，零编排副作用。
- **应用走分离编排进程**：更新应用不在 daemon 或 dashboard 进程内执行——触发方 spawn 平台化分离的短命编排进程（POSIX setsid + double-fork，Windows DETACHED_PROCESS），触发方即时返回受理；编排独立完成下载→校验→停→换→起，每步进度/结果写 status.json 供 UI 轮询（ADR-380）。
- **框架换装三段式**：① 下载目标版本制品与 `.sha256` 强校验（package.sh 产物为 `<包名>.sha256` 双行形态取对应行比对，`<资产名>.sha256` 兜底探测），失败即中止、本地安装零改动；② 解压到框架根同级 staging 目录，按制品完整性清单逐项断言硬读面在位（`VERSION`、`schemas/`、`vendor/floorplan/`、dashboard dist、dsh-bundle dist），缺件即中止；③ 停全部服务化进程（同一框架安装上 N 个项目 daemon unit 逐一经 PAL hosting 链解析 + dashboard unit 一并 stop；未服务化场景跳过停步并在结果注明）→ 旧根 rename 为 `.old-<ts>` 保留一代 → staging 同盘 rename 就位为框架根（路径不变）→ 按 stop 逆序起回全部 unit（ADR-381）。
- **根路径不变量**：换装保留框架根路径不变——既有项目 `.fenix/` 骨架内指向框架根的链接与 skills 软链全部原地有效，installer 无需重跑；用户级 `~/.fenix/config.yaml` 与项目 `.fenix/` 不在任何更新写路径上，内容零改写。
- **在飞 run 预检**：换装前按 `.fenix/runs/*.jsonl` mtime 判读在飞（新鲜记录判在飞，超 6 小时空闲上界视为崩溃残留不误报），存在在飞 run 时拒绝执行并提示等待完成——用户已确认仍须过此门；判读以盘面 run 记录为准，不依赖 dashboard 的 active_runs 计数（实测不可信）。
- **失败回滚与幂等恢复**：换装任一步失败 → `.old-<ts>` rename 回原名 → daemon 按原版本重启 → 状态记失败并含失败阶段与原因；回滚副本仅保留一代，下次成功换装后清理更旧代。编排启动时检测残留 staging/`.old-*` 目录与状态文件，按记录续走或回滚（更新中断后的半换装态幂等恢复）。
- **插件更新独立编排**：一键更新同时更新 dsh-plugins：下载 zip（同双腿鉴权与 mirror）+ sha256 校验 → 解压到旧插件目录同级的新版本目录 → 枚举 CLI 可管理 dsh profile（排除 desktop），对 link: 指向旧插件目录的 fenix 插件逐一 `dsh plugin remove` + `add link:<新目录>` 确定性重注册（不对 add 覆盖语义做假设）→ 逐插件验证 `exports` 指向文件存在。非 fenix 插件（loopback-trust 等）零触碰；desktop profile（Electron 专属管理）不自动改写，检出时降级为结果内的桌面版手动更新文档指引；插件与框架更新相互独立，单边失败不阻断另一边。
- **插件目录边界**：link: 目标位于框架根内的插件（源码/工作树形态安装的 `link:<框架根>/dsh-bundle`）不参与独立插件更新——其内容随框架换装一并就位并检出注明；插件新目录解压目标 MUST NOT 落在框架根内（污染框架根，且下次换装被 `.old` 携走成孤儿）。
- **配置面**：用户级 `update:` 段三键——`enabled`（检查开关，默认 true）、`interval_hours`（检查间隔，默认 24）、`mirror`（制品下载镜像前缀，可空）。键缺失/类型非法回退默认值不抛异常；mirror 只替换制品下载 URL 前缀（API 域名不替换），sha256 校验口径不变；配置变更对下一次检查生效。
- **版本门冲突不自动放行**：新版框架与已装 dsh 版本门（peerDependencies）冲突时，更新结果透出 bundle 挂载失败提示并指引既有 `allow-version --accept-risk` 路径，不做自动放行。换装后运行中进程内存代码仍为旧版自洽，更新结果提示刷新/重启 dashboard 以加载新前端 dist。
- **审计留痕**：每次检查与应用追加一行到 `~/.fenix/update/audits.jsonl`（触发来源、目标版本、阶段序列、结果与失败原因、耗时；尽力而为，写失败不阻断主流程），供运维页读侧展示与排障回溯，按既有产物保留策略清理。

## 代码锚点

- 检查引擎与状态面：`core/self_update.py`（版本解析/形态判定、双腿远端查询、检查编排与失败退避、status/audits/lock 路径常量）
- 应用编排与分离进程：`core/self_update_apply.py`（spawn_detached、staging 校验、三段式换装、回滚与幂等恢复、在飞 run 预检、插件重注册）
- CLI 入口：`bin/fenix_update.py`（check/apply/status 三子命令，退出码 0/1/2）
- dashboard API：`core/dashboard/routes/update_routes.py`；运维页更新卡：`core/dashboard/static/src/pages/activities/components/UpdatePanel.tsx`
- daemon 周期挂载：`fenixd.py`（主循环 tick 调 `run_scheduled_check`，异常自吞不中断主循环）
- 停机 unit 解析复用：`core/systemd_hosting.py`（`unit_name_for` / `render_dashboard_unit`）；staging 完整性断言清单同源：`scripts/package.sh`
- 守卫测试：`tests/test_self_update.py`、`tests/test_self_update_apply.py`

## 溯源

- 2026-11-25 add-auto-update（spec/changes/add-auto-update/） — 新建本能力页：版本单源与形态判定、releases/latest 双腿查询、daemon 周期检查与框架级共享状态、运维页更新卡与三个 API、分离编排进程三段式换装、单代回滚与幂等恢复、插件 remove+add 重注册（desktop 降级、框架根内豁免）、`update:` 配置段、审计留痕
