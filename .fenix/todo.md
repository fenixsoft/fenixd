## 2026-09-18

### 可改进
- **verify-serving 存量目录人工清理（fix-verify-serving-disk-reclaim 登记）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 背景：`.fenix/verify-serving/` 存量 19 个 serving worktree 合计约 30G，其中 18 个的 spec 仍存活于 `spec/changes/` 或 `spec/archive/`（按 D1 判据 1「归档等同存活」不会被自动回收），仅 1 个（`verify-draft-fixture-1788860224`）无主已被自动清扫。
  - 清理范围 MUST NOT 只限「spec 在 changes/archive 双双消失」的目录（现测仅 1 个，清理后 30G 基本不动）——**存量主体为 18 个 spec 仍在册目录内各 1.6G `node_modules`**，需按 D1 判据人工逐条核对。
  - 清理方式：**逐条核对后删除，勿用通配批量删**（按 fix-verify-cli-cwd-isolation 教训）：对每个 `<spec>-<ts>` 目录，先确认其 `servers.json` 无登记、`/proc` 无活进程指向、无在飞验证 run，再 `git worktree remove --force` + `git worktree prune`。清理前确认 `.fenix/config.yaml` 的 `verify.deps_mode` 已改为 `hardlink`（本次 SPEC 已改默认值，新建 worktree 单份仅 ~24M），防止存量模式下新建 worktree 再次膨胀。

## 2026-09-19

### 人工运维（fix-artifact-paths-hardcoded-default 登记）
- **对其它已注册项目执行产物配置回填（D5 存量回填，task 7.4）**
  - 背景：产物判定语义已反转（无内置默认集合，未配置=未裁决=判定恒假）。当前机器上除 fenixd 自身（**已裁决为无派生产物**：`worktree.has_build_artifacts=false` + `build_artifact_paths=[]`，落盘 `/root/fenixd/.fenix/config.yaml`，仅本机生效、未入库）外的**所有已注册项目**（其它 daemon 项目主树）尚未回填。
  - **⚠️ 勿照抄本 SPEC task 7.3 的原值**：7.3 写的是 `has_build_artifacts=true + build_artifact_paths=["core/dashboard/static/"]`，该写法**未落地**且实测**有害**——`_rebuild_dist_after_merge` 的触发条件是「static 根下有**非产物**改动」（`is_artifact` 判真即从改动集合剔除），`core/dashboard/static/` 前缀把 `src/` 一并判为产物 → `src_touched` 恒假 → merge 后 dist 永不再重建，常驻 dashboard 停留在旧 UI。本机实际落盘 `false`（等价「不豁免任何路径」，重建照常触发），是规避该缺陷的正确取值。语义澄清：该键是**豁免清单**（哪些路径是派生物、merge-back 不必当回事），**不是构建开关**，既不影响构建次数也不影响验证。
  - 操作：对每个已注册项目主树执行
    `python3 <fenixd 仓库>/bin/fenix_detect_artifacts.py --write <项目根>`；
    脚本幂等、不覆盖已显式配置的项目；探测无产物时写 has_build_artifacts=false；
    执行前确认该项目主树无未提交的产物/源码改动（前缀会把 src 一并判为产物，且如上所述会**连带关掉该项目的 dist 重建触发**——若探测前缀覆盖到源码目录，须改用收窄前缀或退回 `false`）。
  - **发布顺序约束（task 7.5，MUST）**：把本语义反转版本部署到某台机器前，该机上**所有**已注册项目 MUST 先完成上述回填——否则 daemon 一启动，未回填项目即落入「未裁决」窗口，其产物被判为语义内容、`core/dashboard/static` 类路径失去豁免。顺序：本仓库（已裁决，见上）→ 同机其它已注册项目（本条目）。

## 2026-09-19

### 失误
- **VerifyPanel 并发改致开关丢失与 stash 冲突**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：设置页「收尾代码质量审查」开关（verify.impl_code_review）的表单绑定在 evo-merge-back-wip-artifact-scope 合并时丢失，Dashboard 约 6 小时（本地 09-18 13:02→19:02）不可见/不可编辑；随后 add-impl-code-review-gate 合并再遇 autostash pop 冲突（同一 VerifyPanel.tsx）留下未应用改动；最终 admin 手工补回绑定并顺带修复「添加产物路径」按钮失效。
  - 证据：提交 80070fbb（09-18 19:02 本地）「补回 verify.impl_code_review 开关的表单绑定——该键在 evo-merge-back-wip-artifact-scope 合并时丢失界面绑定，config_admin.py 侧登记/校验/回显仍在」并修复单个 Form 外 Form.List 致「添加产物路径」点击无反应；2026-09-18T10:02:24Z（本地 18:02）日志 ERROR「'add-impl-code-review-gate' stash pop conflict: files=['core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx'] —— stash 保留，可用 git stash show 找回被丢弃改动」；同批三 spec 均改动该文件（evo-merge-back-wip-artifact-scope 的 ea789573 产物路径可编辑界面、fix-verify-serving-disk-reclaim 的 e2505498 VerifyPanel Switch）。
  - 调查评估：已核实（80070fbb 提交原文 + 日志 38918/38919 行 + 相关提交 stat）：同一窗口三个 spec 连续改动 VerifyPanel.tsx，合并链无文件级串行；evo-merge-back-wip-artifact-scope 合并把代码质量审查开关的 UI 绑定挤丢（config_admin 登记仍在、仅表单绑定缺失，属「配置键须有 Dashboard 界面」原则违例），add-impl-code-review-gate 合并时 worktree 未提交改动入 stash 且 pop 冲突（改动保留可恢复、非丢失）。根因：同文件多路并发修改 + 合并后无 UI 契约自检。结论：执行层合并遗漏 + 无自检，代价为约 6 小时 UI 回归窗口 + admin 手工补回，与 stash 冲突同源并案。
  - 建议：为 Dashboard 设置页关键配置键建立合并后回归断言：验证 VerifyPanel 渲染出的表单键集合必须包含 config_admin 登记的全部布尔配置键（如 verify.impl_code_review），纳入常规测试/merge-back 自检；对同批多 spec 修改同一文件的合并增加冲突提示。

### 可改进
- **verify-serving 存量约 30G 人工清理未处置**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：（未处置，[2026-09-18#可改进#3] 原样延续）未处置：.fenix/verify-serving/ 存量 44 条目，其中 19 个 spec 仍在册目录各含约 1.6G node_modules（合计约 30G）仍占磁盘；deps_mode=hardlink 已生效（新 worktree 不再膨胀），存量清理仍是最大可回收项。
  - 证据：实测 .fenix/verify-serving/ 44 条目，du 逐目录实测 19 个 <spec>-<ts> 目录（如 add-dashboard-help-center-1788528914、fix-dashboard-read-path-performance-1789587033）各 1.6G；.fenix/config.yaml 第 231 行 verify.deps_mode: hardlink；fix-verify-serving-disk-reclaim 提交 e2505498 在 .fenix/todo.md 登记「存量 18G 人工清理（18 个 spec 仍在册 worktree 各 1.6G node_modules）」。
  - 调查评估：已核实（目录实测 + config.yaml）：清理动作仍为人工运维待办、未执行；spec 侧机制（serving 清扫按 D1 判据「归档等同存活」不自动回收仍在册 spec 目录、deps_mode=hardlink 默认防新增膨胀）均已就位。结论：未解决（未处置），磁盘占用维持约 30G。
  - 建议：按 fix-verify-serving-disk-reclaim 登记的方式逐条核对删除：对每个 <spec>-<ts> 目录确认其 servers.json 无登记、/proc 无活进程指向、无在飞验证 run 后 git worktree remove --force + git worktree prune，释放约 30G；勿通配批量删（按 fix-verify-cli-cwd-isolation 教训）。


## 2026-09-20

### 浪费
- **实现 run 成功却因 merge-back 失败整轮作废**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：evo-transient-storm-alert-context 的首次实现 run 已成功收工（64 分钟、117 轮、约 9.94M token、$8.97），却因 merge-back（实现分支合回主树）遭主树本地改动拒绝而整轮作废，分支两条提交未入 main；同日第二 run 重做（88 轮、$5.94）后才合入，单 spec 累计 $14.91、约 1.8 小时，其中 $8.97 与约 1 小时为无产出消耗。
  - 证据：日志 2026-09-19T00:29:39Z（本地 08:29）run metrics 显示 run_id=impl-evo-transient-storm-alert-context-1789773909（该 spec 的实现 run）terminal=success、duration_seconds=3869、cost_usd=8.97；同秒 ERROR「Merge failed for branch …: Your local changes to the following files would be overwritten by merge: spec/changes/evo-transient-storm-aler…」，前置告警「Self-heal (identical) aborted: '…/tasks.md' differs from branch content」；00:30:38Z 出现「Recovery: re-triggering implement for orphan ready」重新派发；01:26:05Z 第二 run（-1789778425）metrics $5.94/88 轮；git log 确认第一 run 分支两条提交（bb2657c0、da135958）不在 main 可达。
  - 调查评估：本事件在处置 evo-transient-storm-alert-context（瞬断风暴告警上下文与自动核销）时暴露。已核实：第一 run 成功（run metrics）但 merge-back 被拒，根因是主树 spec/changes/evo-transient-storm-alert-context/tasks.md 存在本地未提交改动（spec 迭代提交 07:15/07:24/08:40 之间 08:29 触发合流），merge 无法覆盖本地改动；系统把「merge-back 失败」按 run 失败处理，清理分支后整轮重派实现，而不保留已成功的分支仅重试合并。与存量关系：evo-merge-back-wip-overlap-gate（09-02 归档）管「主树 WIP 与分支重叠」形态，本事件是「merge-back 遭遇 spec 目录被外部在飞编辑」的未覆盖变体，与 [2026-09-19#失误#3] 的「spec 在飞被编辑」竞态同源不同机制。结论：一次性 $9 级浪费成立，且「merge-back 失败即重做整轮」的复发敞口明确（同类事件再发生的单次代价为上次实测 $8.97 + 64 分钟 + 9.9M token）。
  - 建议：merge-back 失败时区分「可重试（主树脏/锁定）」与「run 失败」：前者保留已成功分支与产物、等待主树干净后仅重试合并（失败不进 run 实现预算），不重派实现整轮；并在 merge-back 前对 spec/changes/ 目录做卫检查（检测到在飞未提交编辑即顺延等待提交，对齐 evo-recovery-watch-status-recheck 的顺延范式）。

### 失误
- **评审派发同步阻塞主循环 27 分钟**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：spec-review（对 spec 提案做评审的 agent run）派发仍走同步调用链，daemon 重启后 start() 在主循环之前同步 full_scan（启动时全量 spec 扫描），把刚晋升的 add-impl-code-review-tuning 带进评审并在主线程一路同步等待 _run_claude，实测主循环从 18:46:46 起 27 分钟零运转——期间 cancel_run/approve_push/admin_invoke/scheduling_kick 五个文件信号消费者全部停摆、Dashboard「全仓库审查」进度条出现后消失、所有 spec 推进冻结。
  - 证据：fix-spec-review-blocking-dispatch（当日为修此立项的 spec）proposal 原文实证「2026-09-19 … daemon 从 18:46:46 起 27 分钟没有打印过 Entering main loop，主循环一次都没转过」，并记载 py-spy 显示主线程卡在 _run_claude（评审执行的内部实现）为纯同步等待；.fenix/daemon_started 记录 2026-09-19T10:46:45Z（本地 18:46:45）daemon 启动；修复提交 c064b991「评审派发异步化 + full_scan 启动异步化」已存在。
  - 调查评估：在处置 add-impl-code-review-tuning 的评审时暴露。已核实（proposal 取证 + 提交存在）：spec-review 是全库唯一仍在调用栈上同步执行的 agent run，full_scan 又在主循环前同步执行，两者叠加把主循环钉死；同类先例 fix-admin-run-blocks-mainloop（09-08 归档）只修了 administrator 变体，spec-review 链未一并改。与存量关系：fix-spec-review-blocking-dispatch 已立项并在飞（窗口末 implementing，重派 run 为 impl-fix-spec-review-blocking-dispatch-1789833879-a1，即该 spec 的实现 run），评审派发并入派发队列后台线程、full_scan 异步化均在其任务清单。结论：执行层停摆 27 分钟属实，根因是架构缺口，修复 spec 在飞，待落地验证闭环。
  - 建议：推进 fix-spec-review-blocking-dispatch 落地并验证（评审派发入队后台线程 + full_scan 异步化），验收时补一条「主循环心跳/最长无循环告警」，防止同类静默停摆再发且无人察觉。

- **daemon 点号键配置误读致产物裁决失效误发信号**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：daemon 初始化 7 处用 dict.get("a.b") 扁平键读深合并后的嵌套配置恒取兜底值：本项目已显式裁决的 has_build_artifacts=false（产物存在性裁决键）永远读不到，产物判定器永久「未裁决」，merge-back WIP 重叠闸门（merge-back 前对主树未提交改动与分支重叠的检查/stash 机制）每轮误发 build_artifact_paths_missing（产物路径缺失信号）唤起 admin，窗口内即有一例（evo-transient-storm-alert-context 合流时）；且同段读不到的 mergeback_wip_overlap_policy 使显式 block 策略静默降级为 auto，放大后续 stash 丢弃风险。
  - 证据：admin 修复提交 91b1557e「修 daemon 点号键配置误读致产物裁决失效（信号误解）」：fenixd.py 原以 self.config.get("worktree.has_build_artifacts") 读值，resolve_config 深合并后是嵌套 dict，dict.get 按扁平字面键查找恒返回兜底；修复改走 ConfigLoader.get 点号解析并新增 tests/test_daemon_config_read_paths.py（含 AST 静态防线：新增含点号键的 config.get 即红）；日志 2026-09-19T00:29:39Z「build_artifact_paths_missing 信号已写入 (spec=evo-transient-storm-alert-context) — 呼叫 Administrator 起草产物路径配置」，对应 admin 处置 run admin-evo-transient-storm-alert-context-1789778042（该信号唤起的 admin run）。
  - 调查评估：在处置 build_artifact_paths_missing 信号误解时暴露（信号本身是误报）。已核实 91b1557e 全文与日志：根因是 daemon 初始化段对点号键的读取形态错误，7 处同形态一并修复；产物裁决「未裁决」使 merge-back 时无任何路径豁免、重叠面扩大，与同日 QualityPanel 交付物两次被 stash 自愈丢弃直接相关（见下条）。与存量关系：本项目 .fenix/config.yaml 已落盘 has_build_artifacts:false 但此前生产上不生效，说明 [2026-09-19#人工运维#1] 产物配置回填只有在本次修复后才有实际意义。结论：一次性编码失误 + 无静态防线，已修复且 AST 防线覆盖防复发。
  - 建议：无需新增动作（91b1557e 已修 7 处并加 AST 静态防线）；可将「配置显式值生效性」纳入 daemon 启动自检（启动时校验已裁决键读入值与 config.yaml 一致），避免同类静默失效再次发生。

- **QualityPanel 交付物两次被 stash 自愈丢弃**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：设置页 QualityPanel.tsx（承载「周期性代码审查」开关等配置界面）在本窗口两次交付物丢失：12:17 项目页「质量」分面开关首丢，20:33 设置页「质量」页签的周期性代码审查开关卡片再丢，后者约 9 分钟由 admin 从 stash（git 暂存的改动）手工找回（commit 978f9f65），前者由后续实现轮次补回——为 [2026-09-19#失误#2]（VerifyPanel 并发改致开关丢失）同类复发两起。
  - 证据：admin 找回提交 978f9f65 正文自述「该文件两次交付物丢失同因：add-code-review-agent-and-quality-tab 的 5.7（分面开关）在 12:17 首丢一次，本次（20:32）把设置页『质量』页签的第二张卡片再丢」，找回动作含恢复 Form.Item code_review_enabled 与 handleSave 写回 code_review 子段、npm run build 通过；日志 2026-09-19T12:33:13Z「Stash pop conflict self-healed; discarded stash changes on 1 file(s): [QualityPanel.tsx] (stash preserved, recover via: git show 7cd88ca8…)」；日志 12:32:46Z 记录 WIP overlap gate（policy=auto，即默认策略）把 6 个重叠文件收入 stash。
  - 调查评估：在 add-impl-code-review-tuning 合流时暴露（第二起）。已核实 978f9f65 与日志：根因是 merge-back 前 WIP 重叠闸门在 auto 策略下把主树未提交改动 stash，merge 后 pop 在 QualityPanel.tsx 冲突，自愈逻辑直接丢弃 stash 版（仅留 git show 口令供找回）；该文件窗口内两度被同批多 spec 并发修改，故两度命中。与存量关系：[2026-09-19#失误#2] 同根（上次 VerifyPanel 开关丢失），其建议的「合并后配置键回归断言」与「同文件多路修改冲突提示」均未落地，故判未闭环；另 91b1557e 证实此前显式 block 策略因配置误读未生效，加剧了丢弃面。结论：复发两起、机制缺口确认，建议立项补自愈回归通道。
  - 建议：① 在自愈「丢弃 stash 版」前改为三态重试（pop 冲突 → 用 merge 而非丢弃、或自动创建恢复 commit 留审计、或保留冲突文件并登记 disposition）；② 为 Dashboard 设置页建「表单键集合须覆盖 config_admin 登记键」的合并后回归断言（覆盖 verify.impl_code_review / admin.code_review.enabled 类开关）；③ 对同批多 spec 修改同一文件在 merge-back 前给出冲突提示。

### 可改进
- **每日自省 run 统计只计未归档在跑记录**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：本窗口有 10+ 个实现/评审 run 完成并归档，而每日自省摘要「总 run 数: 1、成功 0、失败 0」——run 统计实际只反映 .fenix/runs/ 当前目录里尚未归档的记录（即只剩在飞 run），窗口内的成功/失败/成本全部不可见，本窗口最大浪费（transient-storm 白跑 $8.97 双 run）在框架汇总层面无迹可循，同类浪费的每日观测持续丢失。
  - 证据：core/self_review.py:272 collect_runs_stats（近 24 小时窗口 runs 统计函数）只 glob .fenix/runs/*.jsonl，不读 .fenix/runs/archive/；日志 2026-09-19T10:17:09Z「runs 保留: 终态 run 移入归档」证实终态 run 即刻移出当前目录；.fenix/runs/archive/ 现有 50 个归档运行文件，其中窗口内完成的有 impl-evo-transient-storm-alert-context-1789773909/-1789778425、impl-evo-frozen-scenario-contract-versioning-1789774274、impl-evo-deliverable-declaration-drift-align-1789774839、impl-evo-spec-concurrency-flight-guard 系列 4 个、impl-add-code-review-agent-and-quality-tab 系列 2 个等，与摘要「总 run 数: 1」直接矛盾；.fenix/runs/ 当前仅剩在飞 impl-fix-spec-review-blocking-dispatch-1789833879-a1。
  - 调查评估：该统计函数口径与每日自省窗口语义不符：窗口内完成的 run 因已归档而不计入，只有「跨窗口仍在飞」的 run 被计为 running。已核实（源码 + 归档目录对照）。根因：归档时机（终态即移）早于自省统计时点，统计未把归档清单（runs-archive-manifest）纳入窗口归属判定。与存量关系：无既有 spec 覆盖（此前摘要数字在低并发时段刚好与直觉一致，未暴露）。结论：观测面缺口成立，直接削弱自省做浪费/成本归因的能力，值得立项补归档并集统计。
  - 建议：collect_runs_stats 改为「.fenix/runs/ 当前文件 + runs-archive-manifest 归档记录」并集，按 run_id 内嵌开始时间戳统一判定窗口归属，使窗口成功/失败/成本/秒挂/超时统计与归档实际一致。

- **verify-serving 存量 30G 人工清理仍未执行**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：（新增）[2026-09-18#可改进#2] 与 [2026-09-19#可改进#3] 原样延续未处置：.fenix/verify-serving/（验证服务 worktree 目录）仍有 48 个条目、合计 30G 磁盘占用（其中 19 个在册 spec 目录各含约 1.6G node_modules），是本机最大可回收项；磁盘当前 78% 使用、可用 50G，尚未形成压力但持续占用。
  - 证据：实测 .fenix/verify-serving/ 共 48 条目、du 合计 30G；.fenix/config.yaml 第 126 行 has_build_artifacts: false、verify.deps_mode 已为 hardlink（防新增膨胀）；窗口内无对应清理提交。
  - 调查评估：已核实（目录实测）。清理为人工运维待办、未执行，机制侧（serving 清扫按 D1 判据不自动回收在册 spec 目录、hardlink 防新增）均正常。与存量关系：无新增 spec 覆盖，需按 fix-verify-serving-disk-reclaim 登记方式逐条核对删除。结论：未解决，磁盘占用维持约 30G。
  - 建议：按登记方式逐条核对后删除：对每个 <spec>-<ts> 目录确认 servers.json 无登记、/proc 无活进程指向、无在飞验证 run 后执行 git worktree remove --force + git worktree prune，释放约 30G；勿通配批量删。

- **其它已注册项目产物配置回填未执行**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：（新增）[2026-09-19#人工运维（fix-artifact-paths-hardcoded-default 登记）#1] 未执行：除 fenixd 自身外的 4 个已注册项目主树（activation-showcase / fenix-desktop / fenix-server / scheduling-showcase）config.yaml 均无 has_build_artifacts 条目，若部署产物语义反转版本（未配置=未裁决=判定恒假）后 daemon 启动，这些项目即落入「未裁决」窗口、产物路径失去豁免，复发敞口为 merge-back 误判/误发信号（上次同类实测见 91b1557e 前的 build_artifact_paths_missing 误发）。
  - 证据：实测 /root/{activation-showcase,fenix-desktop,fenix-server,scheduling-showcase}/.fenix/config.yaml 均无 has_build_artifacts / build_artifact_paths 条目；fenixd 自身已裁决（.fenix/config.yaml:126 has_build_artifacts: false）；91b1557e 证实修复前 daemon 连已裁决值都读不到，回填需在本次配置读取修复生效后才真正生效。
  - 调查评估：已核实（四项目配置文件 + 本仓 config）。为发布顺序约束（task 7.5 MUST）的前置运维项：部署前须完成回填，否则未回填项目产物判定失效。与存量关系：91b1557e（本窗口已合入）修复了读配置侧，回填动作仍缺。结论：未解决（未处置），需按登记脚本逐项目执行。
  - 建议：对每个已注册项目主树执行 python3 <fenixd 仓库>/bin/fenix_detect_artifacts.py --write <项目根>（幂等、不覆盖已显式配置项）；执行前确认该项目主树无未提交产物/源码改动，探测前缀若覆盖源码目录须改用收窄前缀或退回 false，避免连带关掉该项目的 dist 重建触发。
