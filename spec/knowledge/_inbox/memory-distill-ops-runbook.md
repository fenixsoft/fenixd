# memory 存量蒸馏：运维与取证操作手册

## 背景

交互会话 auto-memory（`~/.claude/projects/-root-fenixd/memory/`，250 文件存量消化，
用户 2026-11-04 指示手动完成）中的**操作配方与运维手册类**知识——从未走 SPEC 管线，
属人类不可见的隐性知识。本条目是操作层（非代码规则）配方的合集，适合折叠进
knowledge-atlas 或 admin-ops 域的运维/操作类能力页。

## 结论（当前事实与配方）

### daemon/supervisor 进程运维

- 陈旧度唯一凭据：`.fenix/supervisor_runtime.json` 的 `script_hash` 与
  `sha256sum bin/fenixd_supervisor.py` 比对——daemon 是新代码不代表宿主 supervisor
  也是（09-13 实证：daemon 新、宿主旧，只看 daemon 无法发现）。
- `.fenix/daemon_started` 记录 daemon 启动时刻：**契约段/prompt/核心代码改动后，
  核对 daemon 启动时间 vs 修复提交时间**——早于修复提交即在跑旧码（「单测通过≠生产
  生效」实证：total_duration 写码提交后 16 分钟 spec 完成但 daemon 未重启，全库 null）。
- 杀实现器进程必须连杀到 attempt 循环耗尽：外部 kill 会被 agent_runner 误判为
  provider 故障并 resume 重试。
- 停失控重派唯一可靠停靠点=预算闸门：置 `_impl_run_budget_used ≥ budget`
  （如 8/6）→ 闸门派发前置检查即 blocked + 人工告警，死亡豁免回退（`used -= 1`）
  需要先有 run 启动而闸门阻止启动，环闭合。blocked 会被失败处理器踩回 ready、
  死亡豁免会回退预算，都不可靠。
- 恢复失控 spec：需同时重置 `_impl_run_budget_used` 与 status（blocked→ready）。
- 半死态修复：结构化冻结（error 带 `frozen:` 前缀）被 cancel 清 error 后残留
  `frozen: True`——`is_spec_frozen` 失效、API unfreeze no-op，须
  `StateMachine.unfreeze_spec(spec, status=<原状态>)` 直修。

### 冻结与重启纪律

- 人工冻结处方顺序不能反：①`sm.freeze_spec(name, reason)` → ②`touch
  .fenix/restart_request` → 先冻结再重启（防重启窗口重派）；pushed 终态不动。
- 重启前判据是双条件：无在飞 run **且**（code-fix 链）无 code-fix run 在飞——
  「进度文件 running=false」≠worker 收尾（checkpoint disabled 分支先于 worker
  收尾写终态，08 秒差曾误杀在飞批）。快速确认：`ps -eo cmd | grep 'claude -p 你是
  Fenix'`。
- restart 排水窗口=`admin.shutdown_drain_seconds`，run 长寿时等满窗口；冻结不能
  加速重启；想重启快先 run-cancel 卡死 run。
- 用进度/状态文件做「链已安全停驻」判据时 MUST 加第二条件（无该车道 run 在飞）。

### 进程与日志取证

- exit_code=143 成批同刻出现=daemon shutdown 屠杀（SIGTERM 成批，0.3 秒双死实证）；
  仅个位数且离散=CLI 自死于网关错误（网关错误形态恒 exit 1 非 143）。
- run 真实时长：`.fenix/runs/<id>.jsonl` result 事件的 `duration_ms` 不可信（显示
  2.4min 实际 19min 实证），用事件首尾 timestamp 差；daemon 日志 `run code-fix-<id>:
  N rounds` 行 ts 减 run id epoch=真实跨度。日志全 UTC。
- run 流转录前缀不止 `impl-`/`verify-`（planner-plan-/planner-judge-/spec-review-/
  admin-/evo- 等占多数），而 planner 系 **worktree 目录仍用 `impl-` 前缀**——两信号
  互相矛盾。存活判据以进程表（`_spec_process_alive`）为主，MUST NOT 单凭流缺失作
  否定判据。
- 悬空 run 数小时=daemon 非优雅死亡（SIGKILL 连带监督线程），非 CLI 静默死亡；
  对照 supervisor.log SIGKILL 行与 fenixd.log Drain 行。
- ftrace 插桩配方（bpftrace/auditctl 未装时）：`/sys/kernel/tracing` 的
  `events/syscalls/sys_enter_kill|sys_enter_tgkill` + `events/signal/signal_generate`
  （trace 行前缀=执行 kill 的进程上下文；一次 killpg 展开为组内每接收者一条）；
  配合 `faulthandler.register(SIGTERM, all_threads=True)` + atexit 线程 dump 的
  wrapper 可拿被杀瞬间全线程栈（/tmp/repro_sig.py 范式）。
- 杀回归进程组：`awk '{print $5}' /proc/<pid>/stat` 取 PGID，确认 ≠ daemon 组再
  `kill -TERM -- -PGID`（回归子进程阶段 cancel_run_request 无效——回归不是 agent run）。
- daemon 存活时 CLI 死→poll 立即返回 error 终态；「锁冲突」类告警两起取证均为
  同一 run_id 重复派发，非残留锁。
- 网关 192.168.20.3 DNS 自 2026-10-28 失效：批量 dns_probe_failed/解析超时告警
  先查网关 53 端口（`connection refused`），不是 fenixd。临时绕过=Admin drop-in
  `/etc/systemd/network/10-netplan-enp42s0.network.d/99-admin-dns-priority.conf`
  （223.5.5.5 提权），**网关修复后须删该文件并 `resolvectl revert enp42s0`**。

### git/工作区操作

- 主树常年堆积多批未提交决策：「提交改动」必须按 hunk 签名过滤只提本会话改动
  （python 切 hunk 生成 per-file patch → `git apply --cached` → `git diff --cached`
  目检 → commit）；整文件 `git add` 会卷入外来工作破坏 SPEC merge-back 流。
  spec 目录自动提交 hook 会把主树同文件热修顺带卷入上游——主树堆未提交决策时
  任何「自动提交某目录」的 hook 都可能夹带语义改动与下游车道撞车（09-23 实证）。
- dist 回退假象判别（「代码被冲掉」先查这个）：`git diff HEAD -- <file>` 核对工作树
  → grep dist 产物新旧标记定性 → dist 回退只需 `npm run build` 重建。验证 bundle
  新旧：构建期源码被 stash 走时产物 hash 可能不变（内容旧），重建后 hash 必变才算
  带上新码；grep 用 ASCII 功能特征（中文被 minifier 转 `\uXXXX` escape 恒空命中，
  构建为 ascii_only 时中文十六进制位大写如 `u81ea`），页面组件在 async chunk 不在
  umi.js 主包。
- merge-back 手工处置：`git status` 分清 untracked/UU/产物——untracked 备份后移开、
  UU `git checkout HEAD -- <file>` 清（stash pop 型 UU 无 MERGE_HEAD，冲突标签为
  `Updated upstream`/`Stashed changes`；对每文件 `git diff :1:<f> :3:<f>` 判 stash
  侧是否为被交付取代的陈旧副本，是则一键取 HEAD 零损失）；处置后手动
  `git merge --no-ff <branch>`（跨进程勿走 daemon ensure_clean_tree——进程内锁 +
  stash 栈 LIFO 共享会错配），再 `update_spec` 置 implemented 清
  error/_merge_fp/_merge_streak/_retry_count。动手前先 `git diff HEAD..<branch>`
  确认分支已含完整实现。
- autostash 悬空恢复：gate stash 看 `git stash list`；autostash 用
  `git fsck --dangling`（筛 committer date 落事故窗口 + message `pre-dispatch
  autostash` + parents=2），恢复 `git diff <autostash>^1 <autostash> | git apply
  --3way`——**--3way 会静默跳过部分文件（exit 0 但 22/39 被跳过实证）**，必须逐文件
  二次核对补齐（`git diff --quiet HEAD -- <f>` 未生效则 `git checkout <autostash> --
  <f>`）。untracked 不进 stash（2 parents），只能从源头重建。
- **恢复完成后第一动作是 git commit 入库**——恢复与提交之间不留窗口（10-01 实证：
  恢复的 untracked 数分钟内被在飞蒸馏轮的放弃产出 clean 再清一次）；committed 不在
  restore/clean 半径。
- 蒸馏「放弃产出」路径（validate_knowledge 修正轮耗尽 → `git restore
  spec/knowledge/` + 清未跟踪新增）对脏工作区是破坏性清理，会清掉用户 untracked
  文件（ADR md 曾被清 3 份）。
- `.fenix` 是自引用符号链接：`git add .fenix/...` 报 "beyond a symbolic link"，
  运行时经 `.fenix/` 访问、git 操作用真实路径。
- 用户级配置有两处：`~/.fenix/config.yaml`（设置页写此处）≠ 项目仓
  `.fenix/config.yaml`（daemon 直读）——排查 enabled 类问题两处都要看。

### dashboard 验证与运维

- 双向铁律：**分支行为验证**打 worktree 自起实例（`python3 bin/fenix_dashboard.py
  --serve --port 8789`，:8787 常驻进程内存是启动时刻旧码）；**dashboard 类 SPEC 的
  验证目标恰是主树 :8787**（静态实时读盘，重建 dist 后免重启生效）。1900x 是
  agent run 的隔离 dev-server。
- dashboard 重启协议：`tmux kill-session -t fenix-dashboard` 后
  `env -u CLAUDE_PID tmux new-session -d -s fenix-dashboard "env -u CLAUDE_PID
  python3 .../fenix_dashboard.py --serve"`（双保险去 CLAUDE_PID——存活 claude 即装
  watchdog，会话结束实例自杀）。验证三件套：curl :8787 得 200、/proc/<pid>/environ
  无 CLAUDE_PID、chunk 与 dist 一致。
- tmux server 孤儿化变体：`tmux kill-session` 报 no server running 但 8787 仍有旧
  进程监听——直接 `kill <旧PID>` 等端口释放再 new-session；直接 new-session 会因
  端口被孤儿占用静默失败。
- 「显示未配置」类先怀疑陈旧进程：curl `/api/config?project=<名>` 与新进程直跑
  `read_config` 比对，不一致即重启 dashboard（改 Python 读侧不重启恒旧视图，
  dashboard 无 restart_request 通道），**不要改 config.yaml**。
- playwright-cli default 会话是全局单例，与在飞 run 的 UI 验证 agent 共享浏览器
  互相 goto 打架——验证必用 `-s=<任务名>` 命名会话，用完 close。
- 禁止 curl 破坏性 POST 端点验证（clear-todo 等全局动作一经请求立即执行，曾真实
  清空四项目 todo.md）。dashboard API 404 取证看响应体区分路由层/handler 层；
  探测用真实项目名（`__probe__` 假项目必得假阳性 404）。
- 假项目 fixture 验证配方：`HOME=/tmp/xx` 起实例最彻底（registry/扫描根全指临时
  HOME，预写 dashboard.yaml 注册 fixture、`scan_dirs: []`），不烧真实 token。
- worktree 里按 `__file__` 推项目根的脚本会多跳一级：`ln -s <worktree>
  <worktree>/.fenix` 自引用软链或显式 `--project`。

### 验证与 admin 处置操作

- 取消 run 后 spec 卡 `_cancelled_hold`：恢复须 `update_spec` 携带
  status+branch+`_recovery_resume` 三件套，再写 `scheduling_kick` 即时唤醒。
- 恢复保留分支续做：直接写 ready 会绕过 preserve 判定、从 main 克隆新分支丢已完成
  工作——须重建 `_recovery_resume` 态。
- 链路由 admin run 的处置中断取证判据：查 run 名下有无 final 结果记录
  （result ∉ pending/escalated）；归因模板对任何终态写「非成功结论」不读 success
  子型，文案与事实可能相反。
- choice 载荷解卡（fix 落地前的存量配方）：按 alert-resolve 端点四步语义 Python
  直执行（AdminStore check 未 handled → `execute_adjudication_choice(note=载荷JSON)`
  → `mark_handled` → DISPOSITION 留痕），载荷走 `note` 参数。
- 场景文件成对纪律：`test_scenarios.json` × `_scenarios_full.json` MUST 成对改
  （后者是「无理由缺场景补齐」的恢复源），单侧手改后旧定义回填复辟；修订场景正道
  =走 revise_scenario_reverify 载荷路径让执行器成对写回。
- unfreeze 必须**显式传 status**（缺省兜底 ready 是陷阱：先删问题文件再解冻，
  拾取仅 1s）。
- 知识恢复盖戳：纯 `UTC` 形态会被本地时区版正则（`UTC[+-]\d`）拒收，手工转 `UTC+8`。
- supervisor 熔断（supervisor_fused）解熔断前先 `python3 -m compileall` 验证主树
  无瞬时坏文件（10-31 实证：提交版本无辜零 diff，restart 撞上瞬时坏文件即熔断）。

## 证据

- 源记忆：`~/.claude/projects/-root-fenixd/memory/` 下 fenixd-supervisor-ops、
  fenixd-freeze-family、fenixd-run-forensics-family、fenixd-dashboard-ops-family、
  fenixd-mergeback-stash-deadlock-family、fenixd-hunk-surgery-commit-playbook、
  fenixd-stop-runway-redispatch、fenixd-autostash-worktree-wipe-incident-and-recovery、
  fenixd-skill-basepath-anchors-main-tree、fenixd-gateway-dns-dead-admin-dropin、
  fenixd-admin-choice-payload-gap-and-scenario-pairing、
  fenixd-chain-admin-disposition-ledger-gap-1103、fenixd-cancel-hold-resume-recipe、
  fenixd-resume-preserved-branch-recipe、fenixd-frozen-scenario-salvage-incident-and-unfreeze-recipe、
  fenixd-supervisor-fuse-transient-broken-tree-1031 等。
- 现行代码锚点（2026-11-04 复核）：`core/code_fix.py:5066`（进度活口径）、
  `core/code_fix.py:4133`（守卫链 enabled→already_running）、
  `.fenix/hooks/block-main-tree-write.py`（存在）、`.fenix/daemon_started`（存在）、
  `core/dashboard/data/command_center.py:62-67`（knowledge-distiller 收编 ZONE_OPS）。
