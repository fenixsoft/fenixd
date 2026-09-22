## 2026-09-21

### 浪费
- **Stale selfheal 重启风暴：06:19-07:06 连续 27 次重启杀评审 run**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：06:19 至 07:06+ 连续触发 27 次 stale_code_selfheal 重启（窗口内共 93 次），daemon 每 2-3 分钟重启一次。06:33:20 重启时 SIGTERM 杀死正在运行的 add-test-regression-tab 评审 run（仅跑了 3 轮即 Exit 143），该评审的全部工作量（~3 轮对话 + 启动开销）作废。整个风暴期间 daemon 反复执行全量 STATE.md 扫描（每次 270+ spec），造成无意义 I/O 和 CPU 消耗。
  - 证据：fenixd.log 统计："陈旧自愈触发" 窗口内共 93 条，其中 06-07 点 27 条。06:33:20 agent_runner Sent SIGTERM to running agent: spec-review-add-test-regression-tab-1789885982 → 06:33:21 Exit code: 143（3 rounds, median 3.5s）。每次重启间隔约 2-3 分钟（06:19→06:25→06:28→06:30→06:33→06:37→06:41→06:45→06:48→06:51→06:54→06:57→06:59→07:02→07:06），supervisor 日志确认每次都是 restart_request detected — SIGTERM daemon for restart。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard（implementing）与 add-freeze-stop-inflight-agents（reviewing）等 SPEC 期间暴露。已核实 fenixd.log 与 supervisor.log 时间线吻合。根因：stale_code_selfheal 检测到 core/**/*.py mtime 超 baseline 后触发重启，但重启后新进程的 baseline 又立即超（可能有实现中的 worktree 持续向主树提交核心代码，或 evolution checkpoint 修改了 registry.py），形成'重启→检测→重启'正反馈循环。add-stale-code-selfheal 机制缺少'连续重启后冷却'保护——_maybe_stale_selfheal_tick 只在 restart_request 不存在时触发，但 supervisor 每次消费后立即清除文件，导致下一轮检测立刻续上。与既有 SPEC 关系：evo-sigterm-source-tracking-cooldown（已 pushed）覆盖 SIGTERM 来源追踪，但不覆盖重启风暴的冷却节流；add-freeze-stop-inflight-agents 覆盖冻结/删除时停 agent，但不覆盖 daemon 重启场景。结论：这是 stale selfheal 设计层面的冷却缺口，与前述两个 SPEC 互补但未被覆盖。
  - 建议：建议立项 SPEC（如 evo-stale-selfheal-restart-cooldown）：(1) 在 _maybe_stale_selfheal_tick 中增加滑动窗口计数（如 30 分钟内重启 ≥3 次则进入冷却，暂停自愈触发 10 分钟并升级为 admin 告警）；(2) 重启后检测到 mtime 超 baseline 时，若无显式用户提交（git log 区分 implementer worktree merge vs 外部写入），应标记为'自触发型 stale'并抑制重启。

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


## 2026-09-22

### 浪费
- **评审车道 Exit 1 连败 12 次，约 175 轮评审对话作废**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：47 分钟内 4 个 SPEC 的评审 run 连续失败 12 次，约 175 轮对话作废（含 3 次连一轮 API 往返都没建立的 0 轮空转），4 个 SPEC 的评审各被推迟 1.4 小时以上，其中 3 条打满 3 次重试上限并升级人工。
  - 证据：fenixd.log 12 条 ERROR「评审 run 执行失败: claude CLI failed: Exit code: 1」（03:33:24 起、04:20:24 止），轮数合计 175（如 run spec-review-add-code-review-auto-fix-1789958592 33 轮、run spec-review-fix-impl-code-review-writepath-1789958599 36 轮、run spec-review-add-timeline-gate-failure-display-1789958599 35 轮）；3 条 escalation「评审尝试已达上限（3）」（a927beb26c2e / 6decb74378bd / 1f5ac0ec4764）+ 1 条 critical 信号 daemon_errors 77fbd229557c（错误指纹 af71e31b 十分钟内复现 2 次）。
  - 调查评估：在处置 fix-impl-code-review-gate-readback / fix-impl-code-review-writepath / evo-stale-selfheal-restart-cooldown / add-timeline-gate-failure-display / add-code-review-auto-fix 五个 SPEC 的收尾评审时暴露。已核实：12 条 ERROR、各 run 轮数与 stall 比例、3 条 escalation、1 条 daemon_errors 信号均取自 .fenix/logs/fenixd.log 的脚本聚合；失败形态可辨——3 条 run 报「0 rounds（无 API 往返样本）」（spec-review-fix-impl-code-review-gate-readback-1789961604 / -1789961799 / spec-review-add-timeline-gate-failure-display-1789963414），其余 stall 占比异常高（run spec-review-add-code-review-auto-fix-1789958592 的 33 轮里 stalls>60s=19，即 57%；run spec-review-add-code-review-auto-fix-1789963498 的 6 轮里 4 次 stall，67%）；重试链最终由 attempt=3 之后的新 run 于 04:46–04:49 全部「评审通过 status=repaired」收口，说明非配置性死锁；窗口内 grep「熔断 / circuit / 退避」零命中，未发现 provider 熔断层记录。根因归属：CLI/API 往返侧瞬时不稳定（同一 Exit code + 0 轮样本 + 高 stall 占比），非本仓代码回归。与存量工作关系：spec/changes 活跃区的 fix-spec-review-blocking-dispatch 与 fix-fasttrack-recovery-resume-lane 修的是评审失败后的恢复/续跑路径，不覆盖「重试本身烧掉的轮数」；spec/archive/ 下无同题归档。残余缺口：重试无退避、五条评审挤在同一 47 分钟窗口内并发重试、互为放大器。结论：属瞬时故障，未见必须立项的系统性缺陷，仅「同批并发无退避」可收紧。
  - 建议：为 spec_review 重试加指数退避 + 同批并发上限（连败后每轮退避 60s×attempt），使瞬时故障不再以「12 次连败 ×175 轮」的形式集中烧预算；并把「0 轮失败」在 run 级指标里单列，避免与真失败同读。

- **验证误判 product-bug 逼出第 5 轮空转，人工止损取消 run**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：该 SPEC 当轮跑了两遍各 22 场景的完整验证 + 6 轮 judge 重跑 + 一次 26 轮 Administrator run 失败 + 一次 33 轮 implementer run 被人工取消；截至 03:56 累计 input token 已达 80.01M/100M（80%）、累计成本 $76.79、实现预算用掉 5/6 轮。
  - 证据：02:40:42「judge 重跑硬上限 'add-freeze-stop-inflight-agents'（6 轮）— 冻结为 blocked，等待人工裁决」（escalation judge_rerun_cap 06da94324c53）；03:56:17 Planner 把场景 web-freeze-inflight-stopped-hint 强制重写为 failed (product-bug) 并「原地打回第 1 轮」、派发 used=5/6；04:22:23 人工取消信号 4a5fd9ef5ed6，reason=「该 spec 实现已由人工裁定合并，验证失败系陈旧产物/缓存假失败，停止第 5 轮空转」，被取消的 implementer run impl-add-freeze-stop-inflight-agents-1789962978-a1 已跑 33 轮。
  - 调查评估：在处置 add-freeze-stop-inflight-agents（冻结在飞 agent，状态 pushed）验收时暴露。已核实：02:38–04:25 的完整生命周期取自 fenixd.log——02:38:39 实现成功进入阶段 2 验证，02:40:42 judge 重跑达 6/5 上限冻结 blocked，02:57:53 blocked_stuck（critical）信号 8211d734bd0f 与配套 disposition 落账，03:34 重跑 22 场景验证，03:56:17 Planner 判定并打回第 1 轮，04:22:23 人工取消，04:24:52 人工裁定 spec_done → auto-approve → pushed（main + 分支均推送成功）。根因归属：验证裁决把「陈旧产物/跨轮缓存」造成的假失败判成 product-bug（同点日志尚有「跨轮缓存归因打标 … cached_from_previous_round」与「验证报告闸门：报告属上一轮残留（本轮裁决已变更），已重新合成覆盖」），属裁决层假阳性，由人工裁定推翻——一次性误判，非 SPEC 设计缺口。与存量工作关系：spec/archive/2026-09-19-evo-judge-rerun-stability 建立的正是这条重跑/缓存机制，本处是该机制的残余面；spec/changes 活跃区无同题 SPEC。残余缺口：judge 重跑上限触顶前没有「疑似陈旧产物」的自动降级或回读校验，代价全部由人工兜底。结论：单次误判且人工兜底有效，但「陈旧产物假失败 → 空转整轮」的敞口仍在。
  - 建议：在 judge 重跑上限触顶前增加「陈旧产物嫌疑」前置判据：同场景连续两轮结论翻转且带 cached_from_previous_round 标时，先做一次产物新鲜度回读校验（或直接降级为 inconclusive 转人工），不要直接判 product-bug 打回实现轮。

### 失误
- **漂移通道漏注册门面转发，AttributeError 两次打断派发**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：13:30:44 与 15:13:17 两次把 add-code-review-auto-fix（代码审查自动修复）的派发整轮异常打断（implementing 回滚 ready、「implementer never started」），并消耗 2 次死亡 run 预算豁免；更关键的是 evo-deliverable-declaration-drift-align（状态 pushed）的漂移对齐通道在生产调用路径上完全不可达——任何交付物争议都会崩在这一行，而不是走漂移对齐。
  - 证据：两条 ERROR「Agent run exception: 'PMEngine' object has no attribute '_preclassify_drift'」（13:30:44 与 15:13:17）+ 紧随的「Rolled back 'add-code-review-auto-fix' implementing → ready (implementer never started)」与「预算豁免（死亡 run）… _budget_exempt_runs=2」；调用点 core/pm_engine/dispatch/queue.py:1150 写的是 `self._pm._preclassify_drift(...)`，而转发注册表 core/pm_engine/engine.py `_FORWARDER_REGISTRY`（264-265 行含 `_preclassify_orphan`）无 `_preclassify_drift` 项，`PMEngine.__getattr__`（engine.py:321-335）对未注册名直接 raise AttributeError。
  - 调查评估：在处置 add-code-review-auto-fix 的派发时暴露。已核实：grep 全仓 `_preclassify_drift` 仅两处命中（queue.py:1150 调用、adjudication.py:709 定义于 VAdjudicationMixin），engine.py 注册表零命中；用 `git log -S` 定位引入者为 8c8da14a（evo-deliverable-declaration-drift-align「漂移笔误机械对齐与派发前同源草案收敛检查」）；该 SPEC 在 .fenix/STATE.md 中状态为 pushed。根因归属：新增门面方法时漏登记转发表——实现层失误；暴露的却是系统性缺口（无任何测试断言「生产调用点的门面名可解析」）：tests/test_deliverable_drift_align.py（792 行）直接对真实 Dispatcher 实例调 `_preclassify_drift` 全绿，唯一的契约测试 tests/test_facade_delegation_contract.py 只校验「原转发方法名全集」逐名可解析（facade-inventory.md 为权威清单），新名不在清单内。与存量工作关系：refactor-facade-delegation（spec/changes 活跃区）确立了转发表契约，但覆盖性是清单驱动的，对新方法天然失明——互补而非重复。结论：一次性漏登记 + 清单驱动契约的盲区，两者都要闭合（后者见「可改进」条目）。
  - 建议：在核心转发注册表补 `"_preclassify_drift": ("_dispatcher", "_preclassify_drift")` 并加回归测试；配套把「调用点 ↔ 注册表」覆盖性硬门做成契约测试（见下方可改进条目），使同类漏登记在 CI 阶段显性失败而非在生产派发路径上抛异常。

- **typo 修正落在主树而防洗白对账读实现分支，spec 回滚 ready**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：add-code-review-auto-fix（48/48 任务已完成、累计 $44.98 / 38.4M input token）在 typo 修正提交后仍被判缺件、回滚 ready（_retry_count=1），成为 STATE 终态分布中唯一 ready 的 SPEC；窗口末尾 17:50–18:06 再无任何派发尝试，成果与成本挂起。
  - 证据：17:49:11.176「dispute judge 裁决 typo」→ 17:49:11.211「声明段软化已提交」→ 17:49:11.452 ERROR「交付物守卫触发 'add-code-review-auto-fix'（缺件 …settings/components/CodeFixProgressCard.tsx（missing））」仍是旧路径；git 核实：修正后主树 spec/changes/add-code-review-auto-fix/tasks.md:46 已是 projects/components/，而实现分支 fenix/add-code-review-auto-fix-1790003908 的同一行仍是 settings/components/，且该分支里 core/dashboard/static/src/pages/projects/components/CodeFixProgressCard.tsx 真实存在（git ls-tree 命中）。
  - 调查评估：在处置 add-code-review-auto-fix 收尾合并时暴露，触发源是立项声明的 path typo（声明 settings/components/CodeFixProgressCard.tsx，实现落在 projects/components/）。已核实：17:36:21 守卫判缺件并进 LLM 终审（dispute-judge-add-code-review-auto-fix-1790012181）；17:49:11 裁决 typo 并提交修正，该 commit 为 25bc8da0（仅含于 main，`git branch --contains` 无实现分支）；修正后 adjudication.py:1539 会以 `self._pm._deliverable_gate_missing(spec_name, result)` 重跑守卫对账（design 4.4 防洗白），但重跑仍报旧路径 → 落入 `_redispatch_for_missing`（adjudication.py:1685 的 ERROR 与 ready 回滚即此路径）。根因归属：声明段修正的写侧落在主树，守卫读/对账基准是实现分支（守卫 docstring 明示「校验基准为实现分支提交」），两侧错层使「修正声明 ≠ 生效」——系统性的读/写基准不一致。与存量工作关系：add-declaration-relocation-protocol 与 evo-deliverable-declaration-drift-align 已覆盖漂移定位、机械改写与防洗白，本处恰是防洗白闸门自身的基准错层，属补充空白而非重复。结论：fail-closed 未误放行 merge，代价是该 SPEC 卡在 ready 且下一轮能否自愈无证据；残余缺口是「修正提交未同步到对账基准」。
  - 建议：typo/reference 裁决执行后，MUST 把声明段修正同步落到防洗白对账所用的基准（把修正提交 cherry-pick/checkout 到实现分支，或以修正后的生效声明重建对账快照）后再重跑守卫；并补一条回归：修正后目标文件确实存在时必须放行（本轮该条件已满足却被判缺件）。

### 可改进
- **门面转发缺调用点覆盖性硬门，新方法漏登记无测试可拦**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：复发敞口：漏登记一次就让整条通道在生产调用路径上抛 AttributeError——本轮实测两次打断派发、消耗 2 次死亡 run 预算豁免，而 792 行漂移单测 + 758 行门面契约测试全绿也无法发现。
  - 证据：tests/test_facade_delegation_contract.py 的覆盖性硬门按「原转发方法名全集」逐名断言（文件头注释明示 facade-inventory.md 为权威清单，第 40 行），新方法天然不在清单；唯一调用点 core/pm_engine/dispatch/queue.py:1150 与注册表 core/pm_engine/engine.py:264-265 的差集无任何断言——grep 全仓 `_FORWARDER_REGISTRY` 仅 engine.py 与 refactor-facade-delegation/verification-report.md 命中，tests/ 零命中。
  - 调查评估：在处置 add-code-review-auto-fix 派发崩溃（AttributeError '_preclassify_drift'）时暴露。已核实：grep 确认 tests/ 下无任何引用 `_FORWARDER_REGISTRY` 的测试；spec/changes/refactor-facade-delegation/facade-inventory.md 是权威清单但属静态人工清单，不随新调用点自动更新。根因归属：契约由「清单枚举」定义而非「调用点反推」，任何新增门面方法都绕过门禁——系统性缺口。与存量工作关系：refactor-facade-delegation 仍在 spec/changes 活跃区，本缺口是它的自然延伸（补一个覆盖维度），不与之重复。结论：「未参与该时段工作的 agent」可据此直接起草：门禁 = AST 扫描调用点 vs 注册表键集合做双向差集。
  - 建议：新增契约测试：AST 扫描全仓 `self._pm.<name>` 等门面调用点，断言每个被调的私有门面名都能在对应 `_FORWARDER_REGISTRY` 解析（并反向断言注册表无死项）；失败信息直接给出缺登记的名字与调用文件:行号。可作为 refactor-facade-delegation 的补充任务，或独立 evo SPEC。

- **stale selfheal 连续重启冷却仍未落地，SPEC 0/12 任务未开工**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：复发敞口：本轮虽未复现前日「47 分钟 27 次重启」的量级，但同一机制仍在窗口内触发 3 次「陈旧自愈触发」并以 SIGTERM 杀掉 2 个在飞的评审 run（spec-review-add-code-review-auto-fix-1789963991 / -1789964873，均为 0 轮即被杀）；每次重启的固定代价是整轮 daemon 初始化 + 279 条 SPEC 全量扫描。
  - 证据：fenixd.py `_maybe_stale_selfheal_tick`（1108 行起）全文无冷却/历史重启计数逻辑（grep restart_history / 冷却 / 滑动窗口 零命中，_cooldown_started_at 等字段不存在）；spec/changes/evo-stale-selfheal-restart-cooldown/tasks.md 全部 12 项未勾选、STATE 状态 implementing；窗口内 supervisor.log 4 次 restart_request（02:42:45 / 04:27:25 / 04:30:06 / 15:15:19），fenixd.log 3 条「陈旧自愈触发」（首 02:42:43、末 15:15:18），另 04:27:28 与 04:30:09 两条「Sent SIGTERM to running agent」。
  - 调查评估：该条目承接 2026-09-21#可改进#1（同一根因），SPEC 已于 09-21 11:17 立项（commit c022b786）但尚未开工（本窗口是「已立项未落地」态）。已核实：冷却机制零代码（无 restart_history.jsonl 读写、无 cooldown 分支）、tasks.md 12 项全未勾选。另一面：前日条目中「重启杀在飞评审 run」的根因半边已闭合——fenixd.py 新增 `_review_lane_busy()`（1053 行）并接入 `_is_idle`（1012 行），判据含 has_queued_review / is_review_in_flight 与 LivenessSupervisor.reviewer_in_flight 的进程表判据（可覆盖停滞 run），经 merge 18c394f2 / 收口 225232dc 于 2026-09-22 01:17（本地）并入主树；但该次合并写入 core/pm_engine/** 使 daemon 代码转陈旧（17:17:49 stale_code 告警 14ab554c77f6），窗口内未见随后的重启，故修复尚未被运行中的 daemon 加载（本轮 2 次杀 run 均发生在合入之前）。结论：冷却缺口仍在，SPEC 在飞未落地；「杀评审 run」半边已提交待生效。
  - 建议：按 spec/changes/evo-stale-selfheal-restart-cooldown 既有 tasks.md 推进即可（1.1–1.4 冷却与自触发识别、2.1 _is_idle 补 _running_agents、3.1 测试、4.1–4.2 文档）；建议优先落地 1.2/1.3（滑动窗口计数 + restart_history.jsonl），这是唯一能阻断「重启→检测→重启」正反馈的一步。

- **EIO 不可读路径持续刷屏，发现层无黑名单缓存**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：窗口内 496 条 WARNING 刷屏（/root/GSM8K_200 与 /root/dmla-data 各 248 条，24 条/小时稳定持续，首 02:26:43、末 18:05:48），每条带完整路径与 errno，污染 daemon 日志并抬高检索成本；每次全量扫描都要对这些已知不可读路径重 stat、重记一条。
  - 证据：fenixd.log「发现层跳过不可读路径 /root/GSM8K_200（EIO, errno=5）」与 /root/dmla-data 同款，窗口切片内各 248 条、17 个整点小时无间断；同窗口「Autostash reclaim check failed」0 次（末次为 09-20T04:51:48，故前日条目的 autostash 半边本轮未复现）。
  - 调查评估：承接 2026-09-21#可改进#2。已核实：两条路径的 EIO WARNING 计数、按小时分布与首末时间点来自 .fenix/logs/fenixd.log 的脚本聚合；Autostash reclaim check failed 在窗口内 0 次（仅轮转文件 fenixd.log.1 有 1 条，09-20T04:51:48），故该条目只剩 EIO 一半，autostash 半边可视为未复现。根因归属：宿主挂载的数据集目录 I/O 错误（环境侧外部因素），而发现层未对已知不可读路径做缓存/黑名单（框架侧可修）——系统性缺口。与存量工作关系：spec/changes 活跃区无同题 SPEC；spec/archive/2026-09-21-fix-robustness-edge-cases 处理的是验证健壮性边角，不含发现层路径黑名单。结论：仍需立项，代价是日志质量与扫描开销（正确性无影响），清晰度已足够直接起草。
  - 建议：Registry.discover 增加 EIO 路径缓存（首次 EIO 后写入 .fenix/eio_blacklist.json 并按 TTL 跳过，默认 1 小时，可配置），命中期降为 DEBUG 或不记；并把该黑名单在状态日志中按小时汇总一条，替代逐次刷屏。

### 人工运维（SPEC 激活后执行，对应 spec 的 docs/help 文档）
- **add-impl-selfcheck-model-probe 合入后**：同步修改运行时 `.fenix/config.yaml`——各 agent 类型模型链摘除 `maomaoai + deepseek-v4.1-flash` 条目（近 48h 实测 12 次 unrecognized_model 秒死 run；详见 spec 交付的 docs/help/model-chain-ops.md）。改完 `fenixd` 30s 热更新自动生效。
- **add-pipeline-throughput-governance 合入后**：同步修改运行时 `.fenix/config.yaml`——`agents.max_concurrent: 3 → 5`（观察网关压力与回归锁排队，异常即调回 3；详见 spec 交付的 docs/help/pipeline-throughput-ops.md）。
