# dashboard 配置写面与受控 Radio 的两条工程结论（下载源自选实现，2026-11-28）

## 1. 用户级 config.yaml 写面：未管段也要走 _CONFIG_WRITE_LOCK

- 设置页既有配置写单源：`core/dashboard/data/config_admin.py` `write_config`（公开函数持 `_CONFIG_WRITE_LOCK` 委派 `_*_locked`）——**整文件读-改-写**（mkstemp + `_CONFIG_HEADER_COMMENT` 回写 + fsync + os.replace），只合并受管键白名单，未管段原样保留。
- 新增非受管段写入（本例 `update.mirror`，引擎语义不进设置页受管键体系）时**不得自起 yaml 写面**：必须同锁，否则与设置页保存并发时两个整文件重写互覆盖（读-改-写竞态丢段）。落地形态：`config_admin.write_update_mirror`（公开持锁 → `_write_update_mirror_locked`），守卫与原子写惯例照抄 write_config；校验语义单源留在引擎（`core/self_update.py normalize_mirror`），dashboard 只落盘不重复校验。
- 测试缝：写端 patch `core.dashboard.data.USER_CONFIG_PATH`（门面属性），读端 patch `core.self_update.USER_CONFIG_DIR`——两端指同一 tmp 文件即可做 round-trip。

## 2. 受控 Radio.Group 的「纯 UI 选择态」必须独立 state

- antd Radio.Group 受控 value 从数据推导（本例：命中预设 id→预设 / 非空未命中→custom / 空→official）时，「选自定义但不落盘」的中间态**不能只靠 onChange 设草稿**——value 仍被推导值顶回，Radio 视觉不选中、条件渲染的输入框永远不出现。
- 解法：独立 `customActive` state 并入推导链首位（`customActive ? 'custom' : derived`）；预设点选时 `setCustomActive(false)`。真机 playwright 点选即暴露（snapshot 显示 `[active]` 而非 `[checked]`），纯代码审查难发现。

## 附：本功能的生效链与实测口径

- 生效链：保存 → `~/.fenix/config.yaml update.mirror` → 下一次「一键更新」编排受理时读配置（`self_update_apply` ctx.config.mirror）→ 制品/sha256 下载 URL 前缀替换（API 检查永不走镜像）。无需重启。
- 镜像实测与边界（ghfast.top 推荐/社区镜像易死/无防篡改）见 `docs/help/13-self-update.md`「配置 update.mirror 走大陆镜像」节，不在此重复。

# 缺省镜像通道与下载加固（v0.2.2 通道面，2026-11-28 追加）

## 3. 配置键「缺失」与「显式空串」是两个语义，数据类缺省值不能承载业务缺省

- 用户实证直连 GitHub 制品链路不稳定（Connection reset / 慢速滴流）后，产品决策变为「镜像=缺省通道」。此时 `UpdateConfig.mirror: str = ""` 的数据类缺省（表「未配置」）与 `load_update_config` 读出的 ""（曾表官方直连）撞车——三态只能靠**键存在性**区分：键缺失/非 str → `UPDATE_MIRROR_DEFAULT`；显式 `""` → 官方直连；字符串 → 原样（normalize 校验在写入口，读侧不拒垃圾值以免检查面瘫痪）。
- 落盘面必须配合：`write_update_mirror("")` 从「删键」改「持久化空串键」，否则 UI 选官方后重启又滑回默认镜像。教训：**「未表达选择」与「表达了反选」需要不同的持久化形态**；测试用例名直接写语义（test_explicit_empty_mirror_is_official / test_get_defaults_mirror）。
- 分离进程接线坑：apply 编排进程由 CLI 装配 context（`build_context_from_args` 不注入 config），旧的 `ctx.config.mirror if ctx.config else ""` 会让真实 apply 永远直连——默认通道语义必须 `run_apply_orchestration` 开头 `if ctx.config is None: ctx.config = load_update_config()` 补解析。注入缝里手工构造 ctx 的测试不受影响（config 非 None 不重解析）。

## 4. 下载加固的三个防线与测试注入缝

- 双通道候选单源：`core/self_update.py download_channel_urls(url, mirror)`（镜像在前直连兜底、去重保序、显式官方仅直连不绕道）；`download_and_verify` 与 `_fetch_expected_sha256` 都走它，逐通道 try/except 清半截产物，穷尽才收口 `ApplyError("download")`（文案含 "update.mirror" 保既有断言）。
- 慢速滴流：urlopen timeout 是 socket 空闲超时，滴流永不触发——每 attempt 起 `time.monotonic() + DOWNLOAD_WALL_DEADLINE_S(600s)` 墙钟，read 循环内超限 raise socket.timeout 进既有重试链。
- 干净截断：Content-Length 已知时 EOF 后 `done != total` 直接 `http.client.IncompleteRead` 进重试（不等 sha256 拦——早失败、重试快）；headers 读取用 `getattr(resp, "headers", None)` 防御测试假响应。
- 测试缝：通道回退用 `download_impl` 记 URL 序列（impl 面不套 _download_file 重试，恰一次断言）；墙钟 monkeypatch `time.monotonic` 迭代器 `[0.0, 1e9]` 后续 repeat(0.0)；sha 通道回退传显式 `http_get`（默认 getter 走 `_http_get_bytes`，假响应缺 status 属性会判非 200）；**sha256 硬门是真的——夹具期望值必须 hashlib 出真实载荷哈希**。

## 5. Windows NSSM/sc dashboard 承载兜底

- `collect_hosted_targets` 原 docstring「dashboard unit 为 systemd 专属承载」在 Windows 客户端是换装杀手：用户手工 NSSM 服务（工作目录=旧框架根）不停，rename 句柄锁必败。修复：systemd 未命中 → `windows_service_installed() + windows_service_active()`（`core/systemd_hosting.py`，`sc query` rc==0 + 输出含 RUNNING；STOP_PENDING 不含 RUNNING 子串无歧义）兜底纳管；`_default_stop_units/_default_start_units` 按 `pal.IS_WINDOWS` 分派 sc/systemd（pal.IS_WINDOWS 是平台分支唯一合法替身，proc_utils 先例）。
- 测试：monkeypatch `pal.IS_WINDOWS` 断言 ops 序列；非 Windows 门短路不触 `sc`（`_run_sc` 打桩 boom 断言零调用）。
