## 2026-09-21

### 失误
- **Evolution checkpoint 写坏 registry.py 触发重启风暴加剧**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：06:24:43 Evolution checkpoint failed: 'expected an indented block after function definition on line 167 (registry.py, line 168)'。evo analysis run 修改了 core/dashboard/registry.py 但留下了 Python 语法错误，导致后续 daemon 每次启动 import registry.py 时触发异常，且修改本身刷新了文件 mtime → 立即触发 stale 检测 → 又重启，与 #1 的重启风暴形成闭环。
  - 证据：fenixd.log 06:24:43 ERROR Evolution checkpoint failed: expected an indented block after function definition on line 167 (registry.py, line 168)。当前仓库 registry.py 第 167-168 行为 '@staticmethod' 定义（正常），说明语法错误已被后续提交修复（或 evo run 回滚）。git log -- core/dashboard/registry.py 窗口内无直接提交，错误来源为 evo analysis run 的运行时文件修改。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard 的 implementer 阶段暴露。已核实 fenixd.log、当前 registry.py 内容与 _check_evolution_checkpoint 代码（fenixd.py:1640）。根因：evolution analysis run 有权修改 core/ 下的文件（如 registry.py）以推进自进化，但写入后未做 py_compile 校验即落盘，导致语法错误的代码被持久化。该错误直接加剧了 #1 的重启风暴——daemon 重启后 import registry.py → 成功（修复后）/失败（修复前）→ 不管哪种，文件 mtime 已变 → stale 触发。与 add-freeze-stop-inflight-agents 无直接关系，但与 evo 机制的可靠性缺口相关。结论：evo run 的写入缺少原子性校验，属于实现层面失误。
  - 建议：为 evo analysis run 增加写入后校验：在 _evolution_worker 中，run_evolution 返回成功后，对 evo run 修改过的 core/**/*.py 文件执行 py_compile 验证，失败则 git checkout 回滚并记录 WARNING；或将 evo run 的修改范围限制在 .fenix/ 目录内，不允许直接修改 core/ 源码。

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

### 可改进
- **门面转发缺调用点覆盖性硬门，新方法漏登记无测试可拦**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：复发敞口：漏登记一次就让整条通道在生产调用路径上抛 AttributeError——本轮实测两次打断派发、消耗 2 次死亡 run 预算豁免，而 792 行漂移单测 + 758 行门面契约测试全绿也无法发现。
  - 证据：tests/test_facade_delegation_contract.py 的覆盖性硬门按「原转发方法名全集」逐名断言（文件头注释明示 facade-inventory.md 为权威清单，第 40 行），新方法天然不在清单；唯一调用点 core/pm_engine/dispatch/queue.py:1150 与注册表 core/pm_engine/engine.py:264-265 的差集无任何断言——grep 全仓 `_FORWARDER_REGISTRY` 仅 engine.py 与 refactor-facade-delegation/verification-report.md 命中，tests/ 零命中。
  - 调查评估：在处置 add-code-review-auto-fix 派发崩溃（AttributeError '_preclassify_drift'）时暴露。已核实：grep 确认 tests/ 下无任何引用 `_FORWARDER_REGISTRY` 的测试；spec/changes/refactor-facade-delegation/facade-inventory.md 是权威清单但属静态人工清单，不随新调用点自动更新。根因归属：契约由「清单枚举」定义而非「调用点反推」，任何新增门面方法都绕过门禁——系统性缺口。与存量工作关系：refactor-facade-delegation 仍在 spec/changes 活跃区，本缺口是它的自然延伸（补一个覆盖维度），不与之重复。结论：「未参与该时段工作的 agent」可据此直接起草：门禁 = AST 扫描调用点 vs 注册表键集合做双向差集。
  - 建议：新增契约测试：AST 扫描全仓 `self._pm.<name>` 等门面调用点，断言每个被调的私有门面名都能在对应 `_FORWARDER_REGISTRY` 解析（并反向断言注册表无死项）；失败信息直接给出缺登记的名字与调用文件:行号。可作为 refactor-facade-delegation 的补充任务，或独立 evo SPEC。

### 人工运维（SPEC 激活后执行，对应 spec 的 docs/help 文档）
- **add-impl-selfcheck-model-probe 合入后**：同步修改运行时 `.fenix/config.yaml`——各 agent 类型模型链摘除 `maomaoai + deepseek-v4.1-flash` 条目（近 48h 实测 12 次 unrecognized_model 秒死 run；详见 spec 交付的 docs/help/model-chain-ops.md）。改完 `fenixd` 30s 热更新自动生效。


## 2026-09-23

### 浪费
- **三次 daemon 重启 SIGTERM 杀在飞 run，约 41 分钟工作作废**
  - 影响：三次在飞 run 被重启连带 SIGTERM：add-code-review-auto-fix 实现轮在飞 8 分钟（00:29:32→00:37:41Z）、fix-relocation-writeback-layer 实现轮在飞 12 分钟（01:03:11→01:14:52Z）、自进化分析轮在飞 21 分钟/235 轮（12:23:31→12:44:37Z），合计约 41 分钟对话作废、该 evo 周期水位未推进；两轮实现重派后正落进 provider 瞬断窗口，成为两场全局熔断的失败主体。
  - 证据：supervisor.log 三次「restart_request detected — SIGTERM daemon for restart」（00:37:38 / 01:14:48 / 12:44:33Z）后 3-4 秒内，fenixd.log 各有一条「Sent SIGTERM to running agent」：impl-add-code-review-auto-fix-1790034572-a1、impl-fix-relocation-writeback-layer-1790038991-a1、evo-1790079811（235 rounds, median 1.5s，随后 ERROR「自进化分析 run evo-1790079811 失败（水位不推进）: Exit code: 143」）；三次重启均无「陈旧自愈触发」日志，请求来自 restart_request 协议的其它写入方。
  - 调查评估：在处置 add-code-review-auto-fix 与 fix-relocation-writeback-layer 两 SPEC 的实现轮派发时暴露。已核实：三个 run 的起止时间由 run id epoch 与 SIGTERM/延迟日志交叉吻合；12:44:38Z 落了一条 self-evolution 升级告警（admin_alerts 内 handled=true），40 分钟后继任分析 run evo-1790081383 于 13:24:37Z 落地成功，确认该 evo 周期作废后由下一周期补救、两实现轮最终也各自完成（auto-fix 07:21Z pushed、relocation-writeback b59d46c7 05:14Z 合回）。根因：restart_request（supervisor 优雅重启协议的信号文件）触发的规划性重启，在旧代码上直接 SIGTERM 全部在飞 agent、无排水等待——正是 add-pipeline-throughput-governance D3（agents.run_drain_max_seconds 排水，缺省 60s + checkpoint 旗标广播）针对的缺陷面；该 SPEC 于窗口内 15:07Z 合入（9b9cdf7f），其后 17:46:36Z 的重启（陈旧自愈，即 daemon 检测磁盘代码较新后趁连续空闲自动重启的 selfheal，且新冷却机制在场）未再杀任何 run。结论：三例杀 run 全部发生在排水机制上线前，主缺口已由在飞 SPEC 闭合；残余是排水对 evo 分析车道与 execvp 改名孙进程的覆盖尚无实测回归钉住。
  - 建议：为 restart 排水补一条回归测试：构造在飞 evo 分析 run + implementer run 时 touch .fenix/restart_request，断言 run_drain_max_seconds（缺省 60s）内两 run 不被 SIGTERM、超时才有序终止，且进程表按 cwd/cmdline 能把 execvp 后改名形态（node/ocr 等）计入排水集合。

- **code-fix 第 3 批合回撞同功能热修冲突，车道锁死 68 分钟**
  - 影响：code-fix 车道（自动修复代码审查台账条目的深夜无人值守车道）第 3 批合回与主树热修在 core/code_fix.py 同功能冲突交人工后，车道从 16:38Z 起锁死：16:44/16:57/17:14/17:44 四次派发被「Worktree already active」秒拒，直到 17:46:36Z daemon 重启清内存锁，停摆约 68 分钟、当夜剩余 open 条目全部停等；分支侧对 manual_authorized（手动授权旗标，随 fix-progress.json 持久化、授权整条修复链跑完）的平行实现被「取主树版」整体作废。
  - 证据：fenixd.log 16:38:02Z ERROR「code-fix 第 3 批合回冲突，交人工」；四条 WARNING「Worktree already active for code-review-fix:code-fix」（16:44:46 / 16:57:58 / 17:14:46 / 17:44:46Z）；人工合并提交 9c289ae7（16:50Z）message 自述「解决与主树热修 733d4fdc 的 core/code_fix.py 同功能实现冲突（取主树版）」；git diff c272c209..9c289ae7 显示被弃的分支侧含整段「手动授权链（2026-09-22 事故修复）」实现，与主树热修 733d4fdc（16:06Z，core/code_fix.py 65 行）同功能异措辞。
  - 调查评估：在处置 code-review-fix 车道第 3 批合回时暴露。已核实：时间线为热修 733d4fdc 落主树（16:06Z）→ 批次分支最后提交 c272c209（16:33Z）→ 合回冲突（16:38Z）→ 人工取主树版合并（16:50Z）→ 车道锁死至 17:46Z 重启；add-code-fix-batch-failure-selfheal 的 proposal 引用的正是本事故（16:44/16:57 两次 14ms 拒绝）。根因两层：①「合回主树中」冻结事故被双路并行修复——人工热修直落主树、车道按台账条目独立实现同一修复，互不知情，合回必冲突；②失败批路径「保留 worktree 待人工」且不释放进程内 spec 锁（worktree_manager.create 裸内存判断、refresh_locks 仅 daemon 启动时执行一次），单批失败即全车道死锁。与存量工作关系：②已由 add-code-fix-batch-failure-selfheal（17:24Z 立项，STATE ready 待派发）覆盖——失败批现场即弃+锁释放+fail_count 重试预算；①「人工热修与车道并行实现同一条目」的对账缺口不在该 SPEC 范围。另注：热修 733d4fdc 把 core 代码修塞在「[fenix] spec: add-impl-selfcheck-model-probe」提交里，提交信息与内容不符，本次回溯归因即受阻。
  - 建议：①人工/管理侧热修触碰 code-review 台账相关文件后，同步把对应台账条目标记 resolved（或写入豁免清单），code-fix 选批前对账主树同函数实现，避免重复实现；②热修提交与 spec 提交分离，或在 message 注明附带热修内容，保持归因可查。

### 失误
- **fast-track 结果文件缺 verification 段，154 轮 run 收尾作废重跑**
  - 影响：add-code-fix-item-level-progress 的首个 fast-track run（实现+验证一体快车道）跑满 154 轮、消耗 9.4M input token 后，结果文件因缺 verification 段被硬校验判非法，成功状态作废并整轮重跑（第 2 轮 43 轮后 17:44Z 才合回 f19a252e）；该 SPEC 合计 10.9M input token / $10.02 / 预算 2/6，随后又被 17:46Z 重启打断收尾，至窗口末仍停 implemented。
  - 证据：17:25:37Z agent 侧「fast-track succeeded」（run impl-add-code-fix-item-level-progress-1790095299-a1，154 rounds，stalls>60s=6）同秒 ERROR「fast-track 硬校验失败 …结果文件非法（verification 段缺失或结构不完整）」（窗口内唯一一次）；17:25:38Z 原地重派（预算 used=2/6，复用 worktree），第二 run 17:44:04Z 收尾即合回；STATE 现值 status=implemented、error「Recovered from interrupted state: testing」、_cost_usd=10.02。
  - 调查评估：在处置 add-code-fix-item-level-progress 的 fast-track 收尾时暴露。已核实：两轮 run 的轮数、预算计数与时间线均出自 fenixd.log 与 STATE；代码侧成果经 worktree 复用保留，损失集中在重验收尾与约 19 分钟延迟。根因：长 run（154 轮、6 次 stall）收尾时实现侧未按契约写出 verification 段，硬校验门按设计拦下（门本身工作正常），但恢复动作只有「整轮重跑」一档，没有「定向补写结果文件」的廉价中间路径；随后 17:46:36Z 重启又把刚合回的 spec 打断在 testing 态（恢复器置 implemented）。结论：一次性收尾失误叠加恢复粒度过粗，非系统性缺陷；敞口是收尾文件 malform 概率随 run 时长上升，而重跑代价是全轮重验。
  - 建议：fast-track 硬校验拒绝时先走「定向补全」：复用 worktree 只派一个小 run 按 schema 补写/修复结果文件，校验通过即收口，连续 2 次补全失败再降级整轮重跑；并在实现侧收尾检查单中加「写完结果文件后自读回校验 verification 段存在」。

### 可改进
- **（持续）_preclassify_drift 未注册转发表，漂移通道生产不可达**
  - 影响：复发敞口：任何交付物争议一旦命中漂移分支，派发即抛 AttributeError 整轮回滚（上次实测两次打断派发、消耗 2 次死亡 run 预算豁免）；一行注册至今未落，漂移对齐通道持续不可达已超 24 小时。
  - 证据：core/pm_engine/engine.py 的 _FORWARDER_REGISTRY（门面转发注册表）仍只有 "_preclassify_orphan"（265 行）而无 _preclassify_drift；唯一生产调用点 core/pm_engine/dispatch/queue.py:1267 裸调 self._pm._preclassify_drift(...) 且无 try/except；tests/ 下引用 _FORWARDER_REGISTRY 的仅 test_code_fix.py:1335 单名断言，调用点覆盖性契约测试仍不存在。
  - 调查评估：承接 2026-09-22#失误#1 与 #可改进#1（同根因的「补注册」与「加门禁」两层，合并重述）。本轮复核：注册与调用点差集原样未动，STATE 中 add-code-review-auto-fix 的 _last_dispatch_error 字段仍存着该 AttributeError 原文；窗口内未复现仅因无交付物争议命中该分支（该 SPEC 已由人工裁决收口，不再走争议路径），并非缺陷已修。结论：修复成本一行注册+一个 AST 契约测试，是当前性价比最高的待办；不落地则敞口永续，且 792 行漂移单测全绿也拦不住它在生产路径崩。
  - 建议：补注册 "_preclassify_drift": ("_dispatcher", "_preclassify_drift") 并加回归；同时落覆盖性硬门契约测试——AST 扫描全仓 self._pm.<name> 门面调用点与注册表键做双向差集（反向断言无死项），失败输出缺登记名字与调用文件:行号；可并入 refactor-facade-delegation 或独立 evo SPEC。

- **provider 瞬断两次全局熔断，解封即原样重派无退避**
  - 影响：已发生+复发敞口：两场瞬断风暴（02:04:24Z、02:20:59Z）各冻结全部新 run 派发 600 秒，10 次派发尝试失败作废、全局派发停摆约 20 分钟，波及 add-code-review-auto-fix 与 fix-relocation-writeback-layer 两 SPEC 的实现轮；若不加退避，provider 每次抖动都会以「5 连败→冻结→解封→立即重蹈」的方式收敛。
  - 证据：两条 ERROR「Global transient break TRIGGERED …(5 failures within 600s window)」（transient break，provider 瞬断全局熔断），失败清单 10 条全部 provider=inferaiapi.com（auto-fix ×4、relocation-writeback ×6，01:54:45–02:20:59Z）；02:14:30Z 第一次解封后 100 秒即再吃失败、16 分钟后第二场触发；配套 escalation transient_break_storm ×2（admin_alerts 内均 handled=true）。
  - 调查评估：在处置两 SPEC 实现轮派发时暴露，且 10 次失败的 run 正是三次重启杀 run 后的重派批次（run id 1790040109/1790039698 系列），两类事故互为放大。已核实：失败清单的 run_id/provider/时间戳取自熔断日志全文；熔断动作本身是 fix-provider-transient-backoff D4 按设计保护（避免了更烧预算的连败），属保护成本而非机制失效。根因归属：provider 侧瞬时不可用为外部因素，车道侧缺口是「解封后无渐进退避、立即原样重派同一 provider」且两 SPEC 挤在同一重试窗口。与存量工作关系：add-impl-selfcheck-model-probe（本轮 pushed）已做拒模型识别与链上 failover，但针对 unrecognized_model 秒死，不覆盖可识别瞬断的重试节奏——窗口内 unrecognized_model=0（前 48h 为 12 次）旁证该 SPEC 已生效。结论：残余缺口是瞬断场景的重试节奏治理，清晰度足以直接起草。
  - 建议：为 transient break 增加解封后渐进退避：同一错误指纹解封后首次重派前先等 60s×已解封次数（封顶 10 分钟），或解封后先以单并发探针 run 验 provider 可用再恢复并发；解封时按优先级错峰放行排队 SPEC，避免同批并发重撞。

- **orphaned_state 探针误报 3 连发，每例烧一轮 admin 处置**
  - 影响：已发生+复发敞口：窗口内 3 个 SPEC 在 testing 阶段被 orphaned_state（无活动 run 的孤儿态探测）误报 major 告警——12:13Z add-code-fix-manual-trigger、16:09Z add-pipeline-throughput-governance、17:05Z add-impl-selfcheck-model-probe——每例都触发一轮只读诊断 admin run 落处置记录（admin_alerts 中 orphaned_state disposition 共 6 条）；单次代价是一整个 admin LLM run 的 token 与时延，外加 major 告警进人工横幅的噪声。
  - 证据：admin_alerts.json 窗口内 orphaned_state signal/escalation 3 条 + disposition 6 条；17:05Z 处置记录自述「ocr join 停等 + 探针盲区/版本代差复合假孤儿，等车道硬超时自愈后 spec 自动 pushed」，并以 py-spy 取证到存活 ocr 子进程 PID 1833155/1833166（16:35:42Z 起）——探测器判「无活动 run / 无存活子进程」与进程表事实相反。
  - 调查评估：在处置 add-impl-selfcheck-model-probe 的验证停等时暴露（另两例同型）。已核实：三例均为误报、均以「等车道自愈」收口，未造成状态破坏，代价集中在诊断与告警消耗。根因：探测器的存活子进程枚举覆盖不了 execvp 后改名的形态（ocr 子进程现形为 node/ocr，不在探针子进程树内），叠加 daemon 版本代差（新加的心跳/超时字段在旧代码进程上不生效）；fix-ocr-lane-orphaned-state-misfire（14:35Z 合入，074084bb）修的是「嵌套 fingerprint 产物误判未绑定指纹/门在飞检测补全」变体，而 16:09Z 与 17:05Z 两例发生在其合入之后，属未被该 SPEC 覆盖的残余变体。结论：探测判据与代差兼容是系统性缺口，不修则每轮 ocr 长验证停等都会再烧一轮处置。
  - 建议：orphaned_state 存活判据扩展为进程表按项目 worktree 的 cwd/cmdline 匹配后代进程（覆盖 execvp 改名形态），并把「车道停等注记在场」作为显式豁免判据；探测前先比对心跳字段版本与 daemon 进程 lstart，版本代差期降级为 INFO 不升级告警。
