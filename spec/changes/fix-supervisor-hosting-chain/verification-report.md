# 验证报告：fix-supervisor-hosting-chain

> ⚠️ 本报告由框架于 2026-09-12T08:22:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 35/40 场景通过，5 失败，0 错误（1 个真实产品 Bug）**

40 场景：35 通过、5 失败，聚合为 1 个 major 产品 Bug（托管链：stop/install 端点阻塞逼近 30s 超时 + 并发 stop_daemon 的 SIGKILL 兜底误杀新 supervisor，致托管未成立、approve 信号无人消费）。上轮 verdict_cache 的选择器缺陷本轮已修复（click 成功），失败形态与上轮不同，非场景文件问题。

| 指标 | 数量 |
| --- | --- |
| 通过 | 35 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 28.49M |
| 本链增量 Token（输出） | 0.28M |


## 真实产品 Bug

### BUG-01（severity=major）· element_not_exist / json_output / status_code

- 关联场景：web-overview-install-hosting-click、cli-verify-showcase-managed-after-install、api-install-hosting-managed-idempotent、api-lifecycle-start-stop-normal、cli-verify-showcase-approve-signal-consumed
- 描述：安装托管后 supervisor 进程未存活、托管未成立：install-hosting/stop 端点处理阻塞逼近 30s 超时线，并发 stop_daemon 的 SIGKILL 兜底杀死新拉起的 supervisor，daemon 死亡致 approve 信号无人消费
- 根因：stop_daemon 收口过慢（写 .fenix/stop→SIGTERM daemon→轮询上限 30s；daemon 侧 wait_for_running_agents 默认 grace 窗口收口实测约 10-21s）逼近客户端 30s 超时线；上一场景 install 的 stop_daemon 与下一场景 stop 的 stop_daemon 并发互踩，后者超时走 kill-session + SIGKILL 兜底时杀死前者刚拉起的 supervisor（supervisor.log 两次启动均无退出日志即消失）；托管未成立后 daemon 死亡，approve_push_request.json 无人消费
- 证据（场景 web-overview-install-hosting-click 结构化证据，引用）：
  - failed_assertions: [{"type": "element_not_exist", "selector": ".ant-list-item:has-text(\"scheduling-showcase\") >> :has-text(\"运行中·未托管\")", "expected": "安装托管后未托管角标不存在", "actual": "元素仍存在：点击「安装托管」并等待 12s 后项目卡片仍显示「运行中·未托管」"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-supervisor-hosting-chain/screenshots/web-overview-install-hosting-click_assert_fail.png"]
  - first_failed_step: 步骤5（点击「安装托管」后等待 12s）→ 断言 element_not_exist 失败：install-hosting 端点（server 端 stop_daemon 收口约 10-21s，逼近 30s 超时线）未在 12s 等待窗口内完成托管转入，UI 仍显示未托管


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-supervisor-root-explicit-flag | supervisor 目标项目根解析优先级（supervisor-hosting D1）：--project-root 参数优先于 cwd。在 cwd=scratch/cwd-proj 下以 --project-root target-proj 解析，结果 MUST 为 target-proj 且来源标注含「参数」。功能出处：bin/fenixd_supervisor.py:29-45（_resolve_project_root 三级解析，参数优先）。 | pass | 0/3 | - |
| cli-supervisor-root-env-fallback | supervisor 目标项目根解析优先级（supervisor-hosting D1）：FENIX_PROJECT_ROOT 环境变量优先于 cwd。无 --project-root 时设置 FENIX_PROJECT_ROOT=env-proj，解析结果 MUST 为 env-proj 且来源标注含「环境变量」。功能出处：bin/fenixd_supervisor.py:42-44（env 次优先）。 | pass | 0/3 | - |
| cli-supervisor-root-symlink-guard-accident | supervisor 项目根 cwd 兜底不被软链劫持（supervisor-hosting D1 事故回归）：子项目 .fenix/bin -> 主树 bin 软链下，无参数启动（cwd=子项目）解析结果 MUST 落在子项目根，MUST NOT 跟随软链回主树。功能出处：bin/fenixd_supervisor.py:37-45（移除 Path(__file__).resolve() 派生，仅 cwd/参数/env 锚定）。 | pass | 0/3 | - |
| cli-supervisor-invalid-dir-guard | supervisor 启动守卫（supervisor-hosting D1）：目标根无 .fenix/ 时 MUST 打印含解析来源的可读错误并以非零码（2）退出，不产生任何 daemon 进程、不写入 supervisor_runtime.json。功能出处：bin/fenixd_supervisor.py:199-208（FENIX_DIR 不存在 → stderr FATAL + sys.exit(2)）。 | pass | 0/6 | - |
| cli-supervisor-runtime-five-keys | supervisor 运行时自报扩展（supervisor-hosting R2）：_write_supervisor_runtime 原子覆写 supervisor_runtime.json，除既有 sigkill_wait/started_at 外 MUST 含 pid（自身 pid）、script_hash（脚本 sha256）、project_root（绝对项目根），且临时文件+rename 原子写不残留半截临时文件。功能出处：bin/fenixd_supervisor.py:141-181（_write_supervisor_runtime，tempfile+os.replace）。 | pass | 0/6 | - |
| cli-hosting-state-three-states | 托管态三态判定（supervisor-hosting D3 / daemon-health R1）：有 supervisor = managed；有 daemon 无 supervisor = unmanaged（事故回归核心缺口）；两者皆无 = stopped。功能出处：core/fenix_session.py:226-248（hosting_state 三态）。 | pass | 0/4 | - |
| cli-supervisor-running-proc-unreadable | supervisor_running 容错（supervisor-hosting D3）：/proc 不可读或扫描无命中时 MUST 返回 False 且不抛异常。功能出处：core/fenix_session.py:164-185（supervisor_running，_procs_matching 异常兜底 False）。 | pass | 0/3 | - |
| cli-start-daemon-supervisor-command | 唯一托管启动路径（supervisor-hosting D2 / project-lifecycle-control R1）：start_daemon 的 tmux session 命令 MUST 是 supervisor 托管入口（fenixd_supervisor.py --project-root <root>），MUST NOT 再直接执行 python3 .fenix/fenixd.py。功能出处：core/fenix_session.py:287-291（tmux new-session 命令构造）。 | pass | 0/7 | - |
| cli-start-daemon-idempotent-already | 启动幂等（supervisor-hosting D2 / project-lifecycle-control R1）：is_running 为真时 start_daemon MUST 返回 ok=True + already=True，且不创建第二个 session。功能出处：core/fenix_session.py:274-275（is_running → already 短路）。 | pass | 0/4 | - |
| cli-start-daemon-invalid-project-error | 非有效项目启动报错不产生进程（supervisor-hosting D2 / project-lifecycle-control R1）：缺少 .fenix 或 .fenix/STATE.md 时 start_daemon MUST 返回 ok=False 与可读错误，不产生任何进程。功能出处：core/fenix_session.py:270-273（.fenix / STATE.md 前置校验）。 | pass | 0/6 | - |
| cli-start-daemon-stale-stop-cleanup | 陈旧 .fenix/stop 清理（supervisor-hosting D2 task 3.3）：daemon 与 supervisor 均未在跑时启动清理陈旧 stop 标记；supervisor 仍在跑（停止操作进行中）时不误删。功能出处：core/fenix_session.py:277-284（is_running/supervisor_running 均假才删）。 | pass | 0/5 | - |
| cli-stop-daemon-idempotent-not-running | 停止未运行项目幂等（supervisor-hosting D2 / project-lifecycle-control R2）：is_running 为假时 stop_daemon MUST 返回 ok=True + was_running=False，不写 .fenix/stop、不产生错误。功能出处：core/fenix_session.py:328-329（未运行直接返回）。 | pass | 0/4 | - |
| cli-stop-daemon-graceful-order | 优雅收口停止（supervisor-hosting R5 / project-lifecycle-control R2）：先写 .fenix/stop，仅向 daemon 进程发 SIGTERM（supervisor 见 stop flag 自行退出，SIGTERM 不发给它），finally 清除 stop 文件。功能出处：core/fenix_session.py:331-372（写 stop → 定位 daemon SIGTERM → 轮询 → finally 清 stop）。 | pass | 0/5 | - |
| cli-stop-daemon-timeout-kill-no-orphan | 停止收口超时强制终止（supervisor-hosting R5 / project-lifecycle-control R2）：daemon 30s 内未退出时 kill-session 并对残留 daemon/supervisor 补 SIGKILL，无孤儿残留，无论成败清除 .fenix/stop。功能出处：core/fenix_session.py:353-371（超时 kill-session + SIGKILL 兜底 + finally 清 stop）。 | pass | 0/6 | - |
| cli-drain-zero-supervisor-missing-alert | drain=0 项目仍检出无 supervisor（supervisor-hosting D4 事故回归 / daemon-health）：admin.shutdown_drain_seconds=0 且无 supervisor 时 daemon 启动自检 MUST 无条件执行存在性检查——日志落「未受 supervisor 托管」WARNING，admin_alerts 新增 signal_type=supervisor_missing 的 major 告警（描述含 restart_request，建议含安装托管）。功能出处：fenixd.py:1033-1072（A 存在性无条件执行 + 告警落盘）。 | pass | 0/6 | - |
| cli-drain-consistent-silent-managed | 有 supervisor 时自检静默（supervisor-hosting D4 / daemon-health）：drain>0 且 supervisor 在跑、runtime 一致（sigkill_wait 1920 >= 1800+120 余量）时启动自检 MUST 不产生 supervisor 相关 WARNING 或告警。功能出处：fenixd.py:1033-1072（A 存在性通过）与 :1074-1132（B drain 一致性通过）。 | pass | 0/3 | - |
| cli-drain-alert-dedup | 未处置 supervisor_missing 告警去重（supervisor-hosting D4 / daemon-health）：同一未处置告警已存在时重复自检 MUST NOT 追加第二条同类型未处置告警。功能出处：fenixd.py:1053（unhandled_for 判空后再 append）。 | pass | 0/2 | - |
| cli-restart-hook-no-supervisor-fails | restart-daemon hook 消费方校验（supervisor-hosting R7 事故回归）：项目无 supervisor 时 hook 写 restart_request 前 MUST 校验失败（detail 含「无 supervisor，重启请求不会被消费」、不出现「supervisor 将执行优雅重启」假成功字样），且 MUST NOT 写入 restart_request。功能出处：core/hook_engine.py:472-499（_action_restart_daemon 先校验 supervisor_running）。 | pass | 0/5 | - |
| cli-restart-hook-with-supervisor-writes | restart-daemon hook 有 supervisor 时正常（supervisor-hosting R7）：项目有活跃 supervisor 时 hook 写入 restart_request 并返回成功（维持既有行为）。功能出处：core/hook_engine.py:493-499（touch restart_request → 成功）。 | pass | 0/3 | - |
| cli-restart-failed-recommendation-unmanaged-safe | restart_failed 升级建议按托管态分支（supervisor-hosting R8 事故回归）：unmanaged 项目的 restart_failed 告警 recommended_action MUST 不含「启动 .fenix/bin/fenixd_supervisor.py」这类绑定主树的危险直启命令， MUST 含经 Dashboard「安装托管」或 /fenix-setup 恢复托管的指引。功能出处：core/admin_monitor.py:943-960（hosting_state 分支生成建议文案）。 | pass | 0/4 | - |
| cli-restart-failed-recommendation-managed | restart_failed 升级建议按托管态分支（supervisor-hosting R8）：managed 项目的 restart_failed 告警建议 MUST 指引 检查 supervisor 进程与 daemon 排水状态（含「排水」），同样不含直接启动 supervisor 命令。功能出处：core/admin_monitor.py:949-954（managed 分支文案）。 | pass | 0/4 | - |
| cli-legacy-session-compat-running | 旧版固定 session 兼容判定（daemon-health R1）：/proc 不可读、无唯一 session 时回退旧版固定 session fenixd，其 pane 当前工作目录解析后等于项目根即视为 running。功能出处：core/fenix_session.py:49-71（_legacy_session_matches）与 :117-144（is_running tmux 回退）。 | pass | 0/2 | - |
| cli-daemon-health-exception-stopped | 健康检测异常兜底（daemon-health R1/R2）：daemon_health / hosting_state 在检测异常时 MUST 以 stopped 兜底返回，不抛异常（对应 API 层「检测异常不 500」的数据侧）。功能出处：core/dashboard/data.py:2646-2652（daemon_health 异常兜底）与 :2675-2682（hosting_state 异常兜底）。 | pass | 0/3 | - |
| cli-approve-push-unmanaged-reject-no-signal | 审批推送消费方判据升级（supervisor-hosting R10 事故回归，数据层）：unmanaged 项目 request_spec_approve_push MUST 返回带 unmanaged=True 的失败结果（error 含「未受 supervisor 托管」），MUST NOT 写入 approve_push_request.json。功能出处：core/dashboard/data.py:644-657（hosting_state == unmanaged → 拒绝）。 | pass | 0/6 | - |
| cli-approve-push-stopped-legacy-text | stopped 项目审批推送维持既有文案（supervisor-hosting R10）：托管态 stopped 时 request_spec_approve_push MUST 走既有 daemon_down 分支，error 逐字为「daemon 未运行，请先启动 daemon」，不出现托管态文案。功能出处：core/dashboard/data.py:658-663（stopped → daemon_down 既有文案）。 | pass | 0/5 | - |
| cli-normalize-showcase-unmanaged | 状态编排前置：把被测监控项目 scheduling-showcase 归一为 unmanaged（裸 daemon 在跑、无 supervisor）。若受托管（上一轮遗留）先经 stop_daemon 拆托管；若未运行则以裸 daemon 形式启动（python3 .fenix/fenixd.py 直启，与事故现场同构）。归一后 hosting_state MUST 为 unmanaged（daemon=true、supervisor=false）。功能出处：core/fenix_session.py:132-144（is_running）、:164-185（supervisor_running）、:226-248（hosting_state）；被测项目来自 dashboard 全局监控配置 ~/.config/fenixd/dashboard.yaml（name: scheduling-showcase）。 | pass | 0/4 | - |
| api-install-hosting-unknown-project-400 | 未监控项目安装托管返回 400（supervisor-hosting R9 / project-lifecycle-control R3）：对不在监控列表的项目名调用 POST /api/projects/<ghost>/install-hosting MUST 返回 400 与「项目不存在」错误。功能出处：core/dashboard/server.py:1549-1570（_resolve_project_or_400 → None → 400）与 :1586-1589。 | pass | 0/2 | - |
| api-delete-unknown-project-400 | 未监控项目软删除返回 400（project-lifecycle-control R3 异常路径）：DELETE /api/projects/<ghost> MUST 返回 400 与「项目不存在」错误（未知项目名不触发任何停止/忽略列表写入）。功能出处：core/dashboard/server.py:1664-1673（_api_project_delete 解析失败 → 400）、:1774-1778（DELETE 路由）。 | pass | 0/2 | - |
| api-approve-push-unmanaged-409 | 审批推送对 unmanaged 项目返回 409（supervisor-hosting R10 事故回归 / 端点层）：scheduling-showcase 处于 unmanaged（裸 daemon 在跑但无 supervisor）时，对 done SPEC c-sched-done 点击审批推送，POST /api/spec-approve-push MUST 返回 409，error 含「未受 supervisor 托管」与安装托管指引，MUST NOT 写入信号文件。功能出处：core/dashboard/server.py:873-919（_api_spec_approve_push unmanaged 分支 :904-908）、core/dashboard/data.py:644-657（D8 消费方判据）。 | pass | 0/3 | - |
| api-restart-unmanaged-rejected | 对 unmanaged 项目调用 restart 返回可读错误（project-lifecycle-control R3）：scheduling-showcase 处于 unmanaged 时 POST /api/projects/scheduling-showcase/restart MUST 返回 ok=false 且 error 含「未受 supervisor 托管」，请求 MUST NOT 被当作成功重启（不写 restart_request）。功能出处：core/dashboard/server.py:1597-1611（restart 分支 unmanaged 拒绝）与 :1624-1626（ok=false 分支）。 | pass | 0/3 | - |
| api-overview-daemon-hosting-fields | 概览与项目列表含 daemon 与 hosting 状态（daemon-health R2）：GET /api/overview 每个被监控项目 MUST 含 daemon（running/stopped）与 hosting（managed/unmanaged/stopped）字段；在编排后 scheduling-showcase MUST 为 daemon=running + hosting=unmanaged（裸 daemon 可观测为 unmanaged 而非 running）。功能出处：core/dashboard/data.py:2686-2731（project_summary 填充 daemon/hosting :2719-2720）、:3788-3831（overview）。 | pass | 0/6 | - |
| web-overview-unmanaged-badge-menu | 概览项目卡片托管态三态显示与「安装托管」菜单（project-lifecycle-control UI / supervisor-hosting R9 事故回归）：navigate 到 dashboard 概览页（hash 路由出处 core/dashboard/static/config/config.ts:15 history.type=hash；概览页路由 core/dashboard/static/config/routes.ts:10-12 /overview），scheduling-showcase 处于 unmanaged 时其 DaemonBadge MUST 渲染「运行中·未托管」警示样式（ProjectCards.tsx:24-43），项目操作菜单 MUST 含「安装托管」项（ProjectCards.tsx:118-133，仅 hosting===unmanaged 渲染）。 | pass | 0/5 | - |
| cli-approve-push-unmanaged-no-signal-file | 审批推送被拒后无信号残留（supervisor-hosting R10）：409 拒绝后 .fenix/approve_push_request.json MUST NOT 存在（信号不会永久滞留锁死后续审批推送）。功能出处：core/dashboard/data.py:651-657（unmanaged 分支不写文件）。 | pass | 0/2 | - |
| cli-restart-rejected-no-signal-file | restart 被拒后无 restart_request 残留（project-lifecycle-control R3）：unmanaged 拒绝后 .fenix/restart_request MUST NOT 被写入（不会被当作成功重启）。功能出处：core/dashboard/server.py:1605-1611（unmanaged 分支提前返回，不 touch 文件）。 | pass | 0/2 | - |
| web-overview-install-hosting-click | 概览页点击「安装托管」把裸 daemon 项目转入托管（supervisor-hosting R9 事故回归 UI 流 / project-lifecycle-control UI）：在 scheduling-showcase 项目菜单点击「安装托管」（ProjectCards.tsx:126-128 菜单项、:76-98 runAction 调用 installHosting、services/dashboard.ts:83-85），接口成功后 runAction 触发概览刷新；等待安装托管完成（停止裸 daemon → 经 supervisor 启动，见 server.py:1639-1662）后，该卡片托管态徽标 MUST 从「运行中·未托管」变为「运行中」。 | failed（已修正） | 1/4 | product-bug |
| cli-verify-showcase-managed-after-install | 安装托管后项目转入 managed（supervisor-hosting R9 事故回归，跨形态状态验证）：经概览「安装托管」操作后，scheduling-showcase 的 hosting_state MUST 为 managed、supervisor_running MUST 为真，且 .fenix/supervisor_runtime.json MUST 存在并含 pid/script_hash/project_root（project_root 等于该项目根，证明 supervisor 未被软链劫持到主树）。功能出处：core/fenix_session.py:226-248（hosting_state）、bin/fenixd_supervisor.py:141-181（自报五字段）。 | failed（已修正） | 2/7 | product-bug |
| api-install-hosting-managed-idempotent | 已托管项目安装托管幂等（supervisor-hosting R9 / project-lifecycle-control R3）：scheduling-showcase 已 managed 时 再调用 POST /api/projects/scheduling-showcase/install-hosting MUST 返回成功且 already=true（不重启 daemon， 不复用 stop/start）。功能出处：core/dashboard/server.py:1639-1662（_api_project_install_hosting managed 分支 :1653-1654 幂等返回）。 | failed（已修正） | - | product-bug |
| api-lifecycle-start-stop-normal | 概览管理 API 端点 start/stop 正常返回（project-lifecycle-control R3 / R1/R2 端点层）：对已托管项目依次调用 POST /api/projects/scheduling-showcase/stop 与 /start——stop MUST 返回 ok=true + was_running=true（优雅收口， supervisor 见 stop flag 退出），start MUST 返回 ok=true（经 supervisor 托管拉起）。功能出处：core/dashboard/server.py:1755-1763（POST 路由）、:1572-1637（_api_project_lifecycle start/stop 分支）。 | failed（已修正） | - | product-bug |
| api-approve-push-managed-success | managed 项目审批推送正常通过（supervisor-hosting R10）：scheduling-showcase 已 managed 时对 done SPEC c-sched-done 发起审批推送，POST /api/spec-approve-push MUST 返回 200 + ok=true，信号写入后由受托管 daemon 主循环消费（消费验证见 cli-verify-showcase-approve-signal-consumed）。功能出处：core/dashboard/server.py:904-919（managed 放行）、core/dashboard/data.py:665-699（写信号路径）。 | pass | 0/4 | - |
| cli-verify-showcase-approve-signal-consumed | 受托管 daemon 消费审批推送信号（supervisor-hosting R10 后端闭环）：managed 项目信号写入后，daemon 主循环 MUST 在约 2s 粒度拾取并删除 approve_push_request.json（_check_approve_push_requests），并在 fenixd.log 落「消费审批推送信号」日志。功能出处：fenixd.py:796-830（主循环消费）。 | failed（已修正） | 1/3 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

