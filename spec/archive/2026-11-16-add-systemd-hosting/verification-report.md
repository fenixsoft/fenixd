# 验证报告：add-systemd-hosting

> ⚠️ 本报告由框架于 2026-11-04T03:31:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-04T03:31:13.298105+00:00+run-result@mtime1793763073339641267

## 结论：✅ 通过（verified）

**状态：verified — 18/18 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 18/18 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 18 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.91M |
| 本链增量 Token（输出） | 0.20M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sdh-unit-template-naming-exitcodes | 交付单元测试：unit 模板字段与项目名安全化、退出码协议常量成对（pytest 子集）。覆盖：fenixd-<项目名>.service 与 fenix-dashboard.service 模板的 Restart=on-failure/SuccessExitStatus=75/TimeoutStopSec=2100/KillMode=mixed/StartLimitIntervalSec/StartLimitBurst/WantedBy=multi-user.target、dashboard unit 的 Environment=FENIX_DASHBOARD_DETACH=1 与「无 SuccessExitStatus」、项目名点号折叠/非法字符折叠/跨路径哈希唯一；EXIT_CLEAN=0/EXIT_GAVE_UP=75 与 SUPERVISOR_GAVE_UP_EXIT_CODE 成对防漂移。出处：core/systemd_hosting.py:258-334（render_project_unit/render_dashboard_unit）、tests/test_systemd_hosting.py::TestUnitNaming/TestUnitTemplates/TestExitCodeProtocol。注：kill -9 拉回/熔断 75 不拉回需真 systemd 才能端到端观测，验证环境以假 systemctl 承载（task 6.1 约定），由模板 Restart=on-failure + SuccessExitStatus 字段与 StartLimit 兜底配置静态保证（无 fallback 需求，非环境依赖场景）。 | pass | 0/9 | - |
| sdh-start-guards-refusal | start_daemon 启动守卫真模块面（真 core.fenix_session.start_daemon 调用、SYSTEMD_UNIT_DIR 指向验证树内目录，不触真 systemd）：项目根缺 .fenix 软链接返回可读错误「项目根缺少 .fenix 框架软链接」；缺 .fenix/STATE.md 返回「项目根缺少 STATE.md」；systemctl 不可用（PATH 无 systemctl）返回含「需要 systemd」的可读错误。三者均不写任何 unit 文件（unitdir 快照为空）、不产生任何进程、不回退 tmux（tmux 承载退役）。对应 spec「非有效项目启动报错不产生进程」与「systemctl 不可用拒绝启动（tmux 回退退役）」场景。 | pass | 0/8 | - |
| sdh-start-install-enable-idempotent | start_daemon 安装-启用链真模块面（假 systemctl 注入 PATH 留痕调用、SYSTEMD_UNIT_DIR 指向验证树内目录）：未托管项目启动生成安装 fenixd-<安全项目名>-<哈希6>.service 并 daemon-reload + enable --now（各恰一次调用留痕）；unit 文件落盘且含 ExecStart=supervisor --project-root / Restart=on-failure / SuccessExitStatus=75 / EnvironmentFile=- / KillMode=mixed / WantedBy=multi-user.target；daemon 未真实起来时启动探测超时且 unit 不活跃返回可读失败（不谎报成功）；daemon 已在跑时重复启动返回 already=True 且不再发 enable（幂等不重建不重启）。对应 spec「启动未托管项目安装并启用 unit」「重复启动不重复拉起」场景。 | pass | 0/15 | - |
| sdh-stop-hosted-track-graceful | stop 主轨真进程面（真 stop_daemon + 假 systemctl 报已装 + 真 stub daemon：脚本名 .fenix/fenixd.py、cwd 锚定夹具项目根，满足 _is_daemon_proc 结构化判据）：stop 写 .fenix/stop → systemctl stop --no-block 调用留痕（fakectl 日志含该 unit 名）→ stub daemon 见旗标优雅退出 → 轮询确认全退 → 返回 ok=True/was_running=True、.fenix/stop 清除、hosting_state=stopped。对应 spec「unit 承载项目优雅收口停止」场景。 | pass | 0/8 | - |
| sdh-stop-direct-chain-and-idempotent | stop 副轨真进程面（managed-but-no-unit 态）：stub daemon 在跑 + 假 systemctl 报未装——stop 走既有直接信号链（SIGTERM daemon 使 stub 终结），全程零 systemctl stop 调用（fakectl 日志不含 stop --no-block，证不谎报 no-op 成功）、ok=True/was_running=True、旗标清除、hosting_state=stopped；随后对已停项目再次 stop 幂等返回 was_running=False 且不写 .fenix/stop。对应 spec「managed 但无 unit 时走直接信号链」「停止未运行项目幂等」场景。 | pass | 0/11 | - |
| sdh-supervisor-exit-protocol | supervisor 有意退出码协议真进程面（真 bin/fenixd_supervisor.py 子进程）：.fenix/stop 旗标在场启动即以退出码 0 退出（stdout 含「stop flag present — supervisor exiting」，systemd on-failure 对 0 不拉回）；supervisor_runtime.json 五键自报落盘（sigkill_wait/started_at/pid/script_hash/project_root）；项目根缺 .fenix 时 FATAL 可读错误退出码 2 且不写任何 runtime 文件。熔断 75 路径需同 pid 熔断标记（真进程不可构造），由 sdh-unit-template-naming-exitcodes 的常量成对断言与模板 SuccessExitStatus=75 承载（非环境依赖场景）。 | pass | 0/9 | - |
| sdh-migrate-dryrun-running-zero-side-effect | 搬迁脚本真 CLI 面：bin/migrate_to_systemd.py --dry-run 对在跑 stub daemon 夹具项目根实跑（假 systemctl 注入 PATH 不触真 systemd；env -i 最小环境 stub，候选稿摘要只出键名不出值）。断言四阶段编排输出齐备：① 写 unit 文件与 env 候选稿（不 enable，含 unit 全文与 Restart=on-failure 字段）→ ② 拆旧 tmux 承载链与旧 dashboard 实例（旧语义专用路径，[dry-run] 标记）→ ③ env 候选稿提升 + systemctl enable --now → ④ 验收；退出码 0；夹具目录文件快照前后一致（零副作用）、systemd.env.candidate 与 systemd.env 均未落盘。对应 spec「dry-run 无副作用」场景。 | pass | 0/14 | - |
| sdh-migrate-dryrun-stopped-rejected | 搬迁脚本真 CLI 面：--dry-run 对 stopped 态夹具（.fenix/STATE.md 在场、无任何在跑 supervisor/daemon 进程、unit 未装）拒绝迁移——退出码 1、可读错误「项目为 stopped 态且 unit 未安装——不迁移 stopped 项目（env 候选稿以在跑进程 environ 为源，stopped 无源可捕）」。对应 design Non-Goals「不迁移 stopped 项目」。 | pass | 0/4 | - |
| sdh-restart-dashboard-real-tri-state | restart-dashboard 动作真模块面（真 core.systemd_hosting.restart_dashboard_unit + 真 HookEngine 动作方法，仅端口探测 patched，假 systemctl 注入 PATH 留痕）：unit 未安装时 restart_dashboard_unit 返回 skipped 静默（环境态非故障）；unit 已装时动作 success 且写去抖时间戳、同引擎去抖窗内二次触发 skipped（「去抖窗口」语义）；legacy target 非字符串记 failure「配置非法（必须为字符串）」；legacy target 字符串值容忍存在不消费（restart 照常执行）。fakectl restart fenix-dashboard 调用计数恰为 2（unit 已装两相位）。对应 spec「unit 未安装时静默 skip」「legacy target 键容忍不消费」场景。 | pass | 0/11 | - |
| sdh-cli-fenix-session-retired | bin/fenix_session.py CLI 随会话名体系退役真进程面：name 子命令（原默认子命令）与无参数缺省行为均拒绝并指引——退出码 2、stderr 含「tmux 会话名体系已退役」与本项目 unit 名（fenixd-<安全名>-<哈希>.service）；unit 子命令打印 unit 名（fenixd-<名>-<6位哈Hash>.service 形态）；running/path 子命令保持可用（退出码 0）。对应 tasks 3.4 与 docs/help/04-cli.md CLI 条目。 | pass | 0/8 | - |
| sdh-docs-skills-systemd-recipes | 配方与文档 systemctl 化真文件面：skills/fenix-setup/SKILL.md（systemd 依赖检查行、journalctl -u 看现场、人工切换步骤小节、systemctl disable --now 回滚配方）；skills/fenix-dashboard/SKILL.md（systemctl restart fenix-dashboard、journalctl -u fenix-dashboard，且旧 tmux has-session 配方已清零——negate 断言）；docs/help/01-quick-start.md（systemd 依赖行）、04-cli.md（fenix_session CLI 条目退役注记）、06-governance.md 与 07-safeguards.md（唯一托管启动路径 systemd 化、SuccessExitStatus=75）、08-dashboard.md（legacy 目标键退役注记）、09-config.md（target legacy 键不再消费 + restart-dashboard systemctl restart 语义）。对应 tasks 5.2/5.3。 | pass | 0/10 | - |
| sdh-unit-env-denylist | 交付单元测试：unit 运行环境承载（pytest 子集）。覆盖：/proc/<pid>/environ 机械捕获（键集来自在跑进程实环境非白名单）、会话身份 denylist 前缀族过滤（剥离 CLAUDE_PID/CLAUDECODE/CLAUDE_CODE_*/AI_AGENT/IS_SANDBOX/GIT_ASKPASS，保留 ANTHROPIC_AUTH_TOKEN/HTTPS_PROXY/PATH/HOME/API_TIMEOUT_MS 原值）、0600 EnvironmentFile 落盘与 .candidate 候选稿后缀、非法键名/换行值跳过、不可读 pid 抛可读错误。出处：core/systemd_hosting.py:80-251（SESSION_IDENTITY_DENYLIST_PREFIXES/read_process_env/capture_env_candidate）、tests/test_systemd_hosting.py::TestSessionIdentityDenylist。 | pass | 0/7 | - |
| sdh-unit-install-idempotent | 交付单元测试：unit 安装与幂等语义（pytest 子集）。覆盖：unit 已装且服务活跃重复安装返回 already=True 且不重建 unit 不重启服务（零 enable 调用）；未安装时写 unit + daemon-reload + enable --now；enable 失败抛可读 SystemdHostingError；systemctl 不可用返回含「需要 systemd」的可读错误拒绝启动（MUST NOT 静默降级 tmux）；unit 文件落 SYSTEMD_UNIT_DIR 0644。出处：core/systemd_hosting.py:391-413（install_project_unit/install_dashboard_unit）、tests/test_systemd_hosting.py::TestIdempotentInstall/TestSystemctlUnavailable。 | pass | 0/7 | - |
| sdh-stop-dual-track-unit | 交付单元测试：托管停止 systemctl 双轨语义（pytest 子集）。覆盖：unit 已装主轨走 systemctl stop --no-block 且不发直接信号；managed-but-no-unit 走既有直接信号链（SIGTERM daemon）不因 systemctl no-op 谎报成功；systemctl 不可用退化直接信号链不阻断收口；30s 轮询超时对入口快照残留补 SIGKILL（不重扫、补杀前 pid 复用复核跳过防误杀）；停止未运行项目幂等成功不写 .fenix/stop；两条轨无论成败清 stop 旗标。出处：core/fenix_session.py:524-627（stop_daemon 双轨）、tests/test_systemd_hosting.py::TestStopDualTrack。 | pass | 0/8 | - |
| sdh-takeover-exemption-detach | 交付单元测试：dashboard unit 承载实例接管豁免与 DETACH 门（pytest 子集）。覆盖：_parent_is_pid1 判定（PPID=1 → True、非 1 → False、/proc 不可读 → False 偏向放行不自伤、真子进程对照）；FENIX_DASHBOARD_DETACH=1 豁免父子生命周期绑定；PPID=1 且缺 DETACH 孤儿启动拒绝（unit 模板必设 DETACH=1 防无限崩溃循环的前提守卫）。手工 --serve 对 unit 承载常驻实例的「不发信号拒绝接管」面由 serve() 消费 _parent_is_pid1 实现（core/dashboard/server.py:681），真进程 PPID=1 形态需真 systemd 不可达，以判定函数与 DETACH 门测试承载（非环境依赖缺口，验证环境按 task 6.1 约定不触真 systemd）。出处：core/dashboard/server.py:453-597、tests/test_systemd_hosting.py::TestParentIsPid1、tests/test_dashboard_orphan_guard.py::test_detach_env_skips_binding/test_orphan_start_rejected。 | pass | 0/8 | - |
| sdh-restart-dashboard-action | 交付单元测试：内置 pushed → restart-dashboard 动作迁移（pytest 子集）。覆盖：执行侧迁 systemctl restart fenix-dashboard；unit 未安装/systemctl 不可用返回 skipped（静默，不产失败告警）；restart 失败记 failure；成功写去抖时间戳且去抖窗内二次触发幂等 skipped；legacy target 键非字符串按配置非法记 failure、字符串值容忍存在不参与任何执行面；全链hook_config 注入与审计语义。出处：core/hook_engine.py:1418-1495（_action_restart_dashboard）、tests/test_systemd_hosting.py::TestRestartDashboardAction、tests/test_hook_engine.py::TestBuiltinPushRestartDashboard。 | pass | 0/9 | - |
| sdh-migrate-orchestration-units | 交付单元测试：一次性搬迁编排单元面（pytest 子集）。覆盖：retired_session_name 与退役 tmux 会话名派生逐字同口径（旧链拆解打中真实会话的前提）；teardown 旧项目链/旧 dashboard dry-run 零信号零文件副作用；stage1 dry-run 不写 unit 不落 env 候选稿；stage3 候选稿提升（正式 env 缺失以候选稿 0600 补位、已有正式不覆盖）；全编排 migrate(dry_run=True) 对 fixture 项目根零副作用（before==after 快照）；stopped 态且 unit 未装拒绝迁移退出码 1（env 无源可捕，design Non-Goals）。真切换（--execute）为人工步骤，场景不对真切换出题。出处：bin/migrate_to_systemd.py:352-624、tests/test_systemd_hosting.py::TestMigrateScriptHelpers/TestMigrateFullOrchestrationDryRun。 | pass | 0/8 | - |
| sdh-hosted-start-stop-regression | 存量承载测试迁移回归（pytest 子集，supervisor-hosting delta）。覆盖：start_daemon 以 supervisor 命令经 unit 托管拉起（ExecStart=supervisor --project-root，daemon 为 supervisor 子进程）、tmux 会话名体系退役、重复启动 already 幂等、非有效项目拒绝不产生进程、陈旧 .fenix/stop 清理（supervisor 存活时保留）、优雅停止顺序（stop 旗标 → SIGTERM daemon → supervisor 收口 → 清旗标）、超时快照补杀不误杀外来 pid、hosting_state 三态（managed/unmanaged/stopped）。出处：core/fenix_session.py:388-385、tests/test_supervisor_hosting.py::TestStartStopHosted/TestHostingState。 | pass | 0/12 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

