## 2026-09-21

### 浪费
- **Stale selfheal 重启风暴：06:19-07:06 连续 27 次重启杀评审 run**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：06:19 至 07:06+ 连续触发 27 次 stale_code_selfheal 重启（窗口内共 93 次），daemon 每 2-3 分钟重启一次。06:33:20 重启时 SIGTERM 杀死正在运行的 add-test-regression-tab 评审 run（仅跑了 3 轮即 Exit 143），该评审的全部工作量（~3 轮对话 + 启动开销）作废。整个风暴期间 daemon 反复执行全量 STATE.md 扫描（每次 270+ spec），造成无意义 I/O 和 CPU 消耗。
  - 证据：fenixd.log 统计："陈旧自愈触发" 窗口内共 93 条，其中 06-07 点 27 条。06:33:20 agent_runner Sent SIGTERM to running agent: spec-review-add-test-regression-tab-1789885982 → 06:33:21 Exit code: 143（3 rounds, median 3.5s）。每次重启间隔约 2-3 分钟（06:19→06:25→06:28→06:30→06:33→06:37→06:41→06:45→06:48→06:51→06:54→06:57→06:59→07:02→07:06），supervisor 日志确认每次都是 restart_request detected — SIGTERM daemon for restart。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard（implementing）与 add-freeze-stop-inflight-agents（reviewing）等 SPEC 期间暴露。已核实 fenixd.log 与 supervisor.log 时间线吻合。根因：stale_code_selfheal 检测到 core/**/*.py mtime 超 baseline 后触发重启，但重启后新进程的 baseline 又立即超（可能有实现中的 worktree 持续向主树提交核心代码，或 evolution checkpoint 修改了 registry.py），形成'重启→检测→重启'正反馈循环。add-stale-code-selfheal 机制缺少'连续重启后冷却'保护——_maybe_stale_selfheal_tick 只在 restart_request 不存在时触发，但 supervisor 每次消费后立即清除文件，导致下一轮检测立刻续上。与既有 SPEC 关系：evo-sigterm-source-tracking-cooldown（已 pushed）覆盖 SIGTERM 来源追踪，但不覆盖重启风暴的冷却节流；add-freeze-stop-inflight-agents 覆盖冻结/删除时停 agent，但不覆盖 daemon 重启场景。结论：这是 stale selfheal 设计层面的冷却缺口，与前述两个 SPEC 互补但未被覆盖。
  - 建议：建议立项 SPEC（如 evo-stale-selfheal-restart-cooldown）：(1) 在 _maybe_stale_selfheal_tick 中增加滑动窗口计数（如 30 分钟内重启 ≥3 次则进入冷却，暂停自愈触发 10 分钟并升级为 admin 告警）；(2) 重启后检测到 mtime 超 baseline 时，若无显式用户提交（git log 区分 implementer worktree merge vs 外部写入），应标记为'自触发型 stale'并抑制重启。

- **02:22 stale selfheal 重启杀死 3 个评审 run 后反复重试又失败**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：02:22:19 stale 自愈触发重启，02:22:23 对 3 个正在运行的 spec-review agent 发 SIGTERM（fix-cr-correctness-1789869398 跑 25 rounds、524b59-1789870538 跑 14 rounds、5f62b5-1789870608 跑 22 rounds），总计 ~61 轮对话白跑。重启后 02:22:28 recovery 自动重新 promote 并派发两批新评审 run（1789870948），02:25:46/47 又以 Exit 143 失败（再烧 14+22 轮）。最终 10:26 用户手动删除这两个 spec（commit 5a1efb2e: '两名评审 agent 已终止'），此前评审 infra_failure 已熔断计数达 3。
  - 证据：fenixd.log: 02:22:19 陈旧自息触发（连续空闲 121s）→ 02:22:23 Sent SIGTERM to 3 running agents → 02:22:24 三个 run 均 Exit 143 → 02:22:27 daemon 重启 → 02:22:28 recovery re-promote → 02:22:28 dispatch 新 run 1789870948 → 02:25:46/47 又 Exit 143 → run_infra_failure triggered: count=3。commit 5a1efb2e（10:26）: '用户指令删除：两名评审 agent 已终止，STATE.md 条目已剔除'。
  - 调查评估：在处置 fix-cr-correctness 系列 SPEC（后被用户 remove 后重建归档）期间暴露。已核实 fenixd.log 时间线、commit 5a1efb2e 内容与 supervisor 重启记录。根因：daemon 持旧代码+连续空闲 121s 触发 stale selfheal 重启，与 #1 同源（stale 检测的空闲判定未考虑正在运行的评审 agent 数量——_is_idle 仅检查 _active_runs，但评审 run 是否计入 pm_engine._active_runs 取决于实现）。重启本身是设计行为，但评审 run 的价值被清零、且恢复路径上的连续失败缺乏退避，最终迫使用户手动干预删除 spec。与 evo-sigterm-source-tracking-cooldown（已 pushed）有关：该 SPEC 实现了信号来源追踪，但此处 SIGTERM 标记为 [shutdown-interrupted]（走既有守卫），属于正确分类而非信号追踪缺口。
  - 建议：两条改进：(1) stale selfheal 的 _is_idle 判定应纳入 agent_runner 的 _running_agents（若任一 run 正在执行中则视为非空闲），避免重启时 kill 在跑 agent；(2) daemon 重启后 recovery 重新派发的评审 run，若上次失败原因为 infra_failure/shutdown-interrupted，应自动增加 dispatch_backoff（如 5 分钟退避），避免连续失败后秒熔断。

### 失误
- **Evolution checkpoint 写坏 registry.py 触发重启风暴加剧**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：06:24:43 Evolution checkpoint failed: 'expected an indented block after function definition on line 167 (registry.py, line 168)'。evo analysis run 修改了 core/dashboard/registry.py 但留下了 Python 语法错误，导致后续 daemon 每次启动 import registry.py 时触发异常，且修改本身刷新了文件 mtime → 立即触发 stale 检测 → 又重启，与 #1 的重启风暴形成闭环。
  - 证据：fenixd.log 06:24:43 ERROR Evolution checkpoint failed: expected an indented block after function definition on line 167 (registry.py, line 168)。当前仓库 registry.py 第 167-168 行为 '@staticmethod' 定义（正常），说明语法错误已被后续提交修复（或 evo run 回滚）。git log -- core/dashboard/registry.py 窗口内无直接提交，错误来源为 evo analysis run 的运行时文件修改。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard 的 implementer 阶段暴露。已核实 fenixd.log、当前 registry.py 内容与 _check_evolution_checkpoint 代码（fenixd.py:1640）。根因：evolution analysis run 有权修改 core/ 下的文件（如 registry.py）以推进自进化，但写入后未做 py_compile 校验即落盘，导致语法错误的代码被持久化。该错误直接加剧了 #1 的重启风暴——daemon 重启后 import registry.py → 成功（修复后）/失败（修复前）→ 不管哪种，文件 mtime 已变 → stale 触发。与 add-freeze-stop-inflight-agents 无直接关系，但与 evo 机制的可靠性缺口相关。结论：evo run 的写入缺少原子性校验，属于实现层面失误。
  - 建议：为 evo analysis run 增加写入后校验：在 _evolution_worker 中，run_evolution 返回成功后，对 evo run 修改过的 core/**/*.py 文件执行 py_compile 验证，失败则 git checkout 回滚并记录 WARNING；或将 evo run 的修改范围限制在 .fenix/ 目录内，不允许直接修改 core/ 源码。

### 可改进
- **Stale selfheal 缺少'连续重启冷却'机制导致无限循环**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 stale selfheal 触发 93 次重启（06-07 点集中 27 次），每次重启间隔仅 2-3 分钟，形成正反馈循环。每次重启执行完整 daemon 初始化 + 全量 STATE.md 扫描（270+ spec），持续约 47 分钟（06:19-07:06），消耗系统资源且无实际效果（代码已是最新的，重启不解决任何问题）。
  - 证据：fenixd.log: '陈旧自愈触发' 共 93 条（06-07 点 27 条）。supervisor.log: 06:19-07:06 共 15+ 次 restart_request detected — SIGTERM daemon for restart，每次 alive 时间仅 300-600 秒（远低于正常运行时长）。_maybe_stale_selfheal_tick 代码逻辑（fenixd.py:1000-1060）：前置检查仅看 restart_request 是否存在（in-flight），supervisor 每次重启后消费并删除 restart_request → 新 daemon 启动 → 120s 后检测到 stale → 再写 restart_request → 循环。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard 期间暴露。已核实 fenixd.log、supervisor.log 与 _maybe_stale_selfheal_tick 代码逻辑。根因：stale selfheal 的触发条件'code_stale + is_idle + restart_request不存在'在每次重启后都满足（supervisor 消费 restart_request 后新 daemon 又检测到 stale），缺少历史重启计数或冷却窗口。系统性缺口：设计时假设'重启后代码变新则 stale 解除'，但实际存在'自触发型 stale'（evo run 修改文件 → stale → 重启 → evo run 又改文件）。与 evo-self-review-runs-archive-stats、evo-merge-back-spec-dir-inflight-guard 等 active SPEC 无直接关系，但影响这些 SPEC 的 implementer 稳定性。
  - 建议：建议立项 evo-stale-selfheal-restart-cooldown：(1) _maybe_stale_selfheal_tick 增加滑动窗口重启计数（如 .fenix/restart_history.jsonl 记录最近 30 分钟内重启次数，≥3 次则进入冷却，暂停自愈触发 10 分钟并升级为 admin escalation）；(2) 检测'自触发型 stale'：重启后 5 分钟内若再次检测到 stale，标记为 self-triggered，仅升告警不触发重启，由人工判断是否为 evo run 循环。

- **Autostash git status 超时 + EIO 磁盘错误持续刷屏**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：04:51:48 git status --porcelain 超时 30 秒（autostash reclaim 失败），04:55 起 /root/GSM8K_200 和 /root/dmla-data 持续报 EIO（errno=5 Input/output error），窗口内共 254 条 EIO 告警（每 5 分钟 2 条，持续 13+ 小时）。发现层每次都尝试 stat 这两个不可读路径并报 WARNING，造成日志刷屏。
  - 证据：fenixd.log 04:51:48 ERROR Autostash reclaim check failed: Command '['git', '-C', '/root/fenixd', 'status', '--porcelain']' timed out after 30 seconds。fenixd.log: EIO 日志首次 04:55:11（/root/GSM8K_200），末次 18:15:16（/root/dmla-data），共 254 条 WARNING（发现层跳过不可读路径）。git count-objects -vH: 90M pack，不算大，超时更可能源于磁盘 I/O 延迟（EIO 环境）。
  - 调查评估：在处置 fix-cr-correctness 归档入库与 add-start-after-scope-config fast-track 完成之间暴露。已核实 fenixd.log 时间线与 EIO 错误数量。根因：宿主 /root 下的 GSM8K_200 和 dmla-data 目录（可能是挂载的外部数据集）磁盘 I/O 错误，导致 git 操作超时；发现层（Registry.discover）未对已知不可读路径做缓存/排除，每 5 分钟扫描时重复触发 EIO + WARNING。autostash reclaim 的 30 秒超时可能是 EIO 导致 git status 挂起。系统性缺口：发现层缺少路径黑名单或 EIO 缓存机制。与当前活跃 SPEC 无直接关系，但影响 daemon 日志质量。
  - 建议：两条改进：(1) Registry.discover 中增加 EIO 路径缓存（如首次 EIO 后将路径加入 .fenix/eio_blacklist.json，有效期内跳过，TTL 可配置，默认 1 小时）；(2) autash reclaim 的 git status 超时从 30s 提高到 60s 或改为异步非阻塞检查，避免影响主循环。
