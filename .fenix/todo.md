## 2026-09-12

### 浪费
- **探针超时仍跑整轮验证首轮作废**
  - 影响：add-spec-approve-push-modal 首轮验证在就绪探针 120s 超时（应用不可达）后仍整轮执行 14 场景，产出 6 通过/1 警告/7 环境伪失败，连带 judge 50 turns 后将 spec 原地打回重新实现（69 turns），该 spec 全流程成本 $39.12 居窗口之首；复发敞口=每次 spawn 后探针失败均整轮空转。
  - 证据：fenixd.log 2026-09-11 02:03:21 UTC「应用可达性: 不可达 — … 就绪探针超时（120s）: http://127.0.0.1:50555/api/projects — timed out」，同秒 02:03:21.953「🚀 开始验证 14 个场景」；02:04:14「阶段2 完成: 14场景, 6通过, 1警告, 7失败」；02:41:40「原地打回第 1 轮」注入修复段。
  - 调查评估：已核实 verification.py 阶段2.5（约 1795 行）：_ensure_app_reachable 结果仅记日志，自愈失败由执行后门禁兜底、不 fail-fast 中止本轮，故探针超时后仍整轮执行。根因=可达性失败未短路本轮验证。与窗口内在飞 add-verify-preflight-gate（12:29 立 spec、20:41 合并，D1 入口存在性预检 / D3 boot.log 兜底取证）互补但未覆盖：preflight 管 spawn 前预检与取证，本缺口在 spawn 后探针失败路径。结论=残余缺口成立，值得立项或并入该 spec 后续轮次。
  - 建议：扩展 add-verify-preflight-gate：就绪探针超时即本轮 env fail-fast 中止（保留半日志与 boot.log 取证落盘），避免整轮场景空转与洗白门禁→升级 admin 的人工链路。

- **fast-track 结果文件缺失连发重派**
  - 影响：两起成功 fast-track 因「结果文件未产出」被整体作废重派：add-turn-limit-anchor-c run1 $8.83（181 turns、19 次 Edit，无提交无结果文件）、add-main-tree-deps-provision run1 $8.91（已全量提交 5 个 commit 仍判死亡）；两 spec 各重置 ready、预算豁免 1/6、自动重派 run2（分别 +$4.49 / +$0.92），直接损失约 $5.4 + 2 次状态回退；复发敞口≈$8.8/次（run1 成本实测）。
  - 证据：fenixd.log 07:06:03.850「Ignoring stale result file /root/fenixd/.fenix/.fenix-run-result.json: spec='add-tasksmd-relint-gate' != 'add-turn-limit-anchor-c'」→ 07:06:03.968「预算豁免（死亡 run）… reason=fast-track no run-result… 状态回退 ready + 自动重试 1/3」；同型 13:48:37 主树残留 spec='add-spec-content-integrity-gate' 触发 add-main-tree-deps-provision 重派；另有 planner-plan artifact gate 同型（10:26:01「exit 0 但结果文件缺失」→ r1 原地重试）。
  - 调查评估：已核实 engine.py _read_implementer_result（725 行）：先读 worktree 内 .fenix-run-result.json，缺位后读主树共享文件，spec stamp 不符即 ignore 返回 None→误判 run 死亡。根因=结果文件契约脆弱：当前 run 未写入正确位置，残留前 spec 文件反而拦截成功收口。与 35706f95（零变更哨交付物守卫：分支零提交⟺已并入主树）同族——main-tree run1 全量已提交却仍重派，恰是该守卫语义未覆盖结果文件缺位路径。worktree 复用（Kept worktree for reuse）部分挽回 turn-limit 损失（run2 62 turns 完成全部 6 任务为证），但状态回退与重派轮成本已发生。结论=系统性契约缺口，值得立项。
  - 建议：将「结果文件缺失→重派」升级为「结果文件缺失 且 分支零提交→重派」（复用 35706f95 交付物守卫语义），分支有提交即按成功收口；daemon 消费主树共享 .fenix-run-result.json 后即时删除，消除跨 spec 残留误拦。

### 失误
- **重启排水强杀实现 run 整轮作废**
  - 影响：impl-add-blocked-reverify-lane-1789107185 在 planned restart 排水窗 1800s 后被 SIGTERM 作废（14:13→16:21 本地运行 128 分钟、0 提交残留），成为窗口唯一 failed run（1/30），尝试预算 1→2/6，自动重派 run2 152 turns 才完成。
  - 证据：supervisor.log 07:51:01 UTC「restart_request detected — SIGTERM daemon for restart」；fenixd.log 08:21:12「Drain finished after 1800s, remaining runs: ['impl-add-blocked-reverify-lane-1789107185-a1']」+「Preserving interrupted run … branch 'none', ahead=0」+ SIGTERM +「implementer failed … Exit code: 143」；08:51:24 Retry 1/3 重派，10:05:22 成功（152 turns）。
  - 调查评估：已核实事件链：框架代码窗口内高频更新（91 commits）使运行中 daemon 规则过期，触发 restart_request 热重载，排水 30 分钟未等 run 自然收口即强杀。被杀 run 无 commit/worktree 登记（branch='none', ahead=0），add-impl-terminal-nocommit-gate 的 stash 留档通道（1.3/2.2 已实现）在此场景未生效。根因=重启策略未对长活实现 run 自适应。结论=执行层可改进项，非系统缺陷。
  - 建议：planned restart 触发时若存在活跃实现 run，排水窗按运行时长自适应（>60min run 给足 3600s）或强杀前先 stash create 留档（复用 add-impl-terminal-nocommit-gate 留档通道），保证中断不丢工作。

- **sed 误转义破坏 tasks.md 勾选行**
  - 影响：add-impl-terminal-nocommit-gate 的 tasks.md 勾选行因 sed replacement 误转义 \^ 丢失前导符，dashboard 任务清单解析为空，需 2ef1938d 一版 12 行修复提交；复发敞口=任何用 raw sed 改 checklist 行均可能重演。
  - 证据：2ef1938d（09-11 10:47 +0800）「修复 tasks.md 勾选行的 ^- 前缀（sed replacement 误转义 \^ 导致 dashboard 任务清单解析为空）」，改动 spec/changes/add-impl-terminal-nocommit-gate/tasks.md 12 行。
  - 调查评估：已核实 commit 内容与时间：落后该 spec fast-track 成功（09:41 本地）约 1 小时，属事后纠偏直接入主树。根因=以 sed -i 文本替换任务行时 \^ 转义失当。窗口内 13:27 已合并 add-tasksmd-relint-gate 的 lint（分组/解析结构校验）但不校验任务行前导符完形，未拦截此类回归。结论=一次性脚本失误，可被 lint 覆盖闭合。
  - 建议：给 add-tasksmd-relint-gate 追加一条 lint：任务行必须以 ^- 前缀（或标准 checklist 前缀）开头，缺前缀即违规报错，使 sed 误转义在实现阶段即被拦。

- **start_after 未到期误报滞留**
  - 影响：add-main-tree-deps-provision 设 start_after 16:00 UTC 定时拾取，未到期期间被假就绪巡检误报 dispatch_stalled：signal 1 条 + 处置记录 3 条（07:29:01 信号、07:33:54/07:56:18 两次处置），召唤 Administrator 占人工注意力；且每 30 分钟被误标 orphan ready 重触发产生噪音事件。
  - 证据：admin_alerts.json 窗口内 dispatch_stalled signal（07:29:01, add-main-tree-deps-provision, severity=major）+ 07:33:54/07:56:18 两条 disposition；修复提交 08a8628a（15:48）自述「每 30 分钟被误标孤儿 ready 重触发一次」「30 分钟即误判滞留并呼叫 Administrator」。
  - 调查评估：已核实告警与修复双向对应：BLOCKER CHECK 假就绪巡检与 event_bus _recover_ready 均未豁免 start_after_pending（与退避/活子进程豁免同语义缺漏）。根因=巡检豁免清单不全。窗口内 15:48 已修复（engine.py + event_bus.py + 2 条回归测试），属已闭环失误。结论=按历史失误记录，防回归即可。
  - 建议：已修复（08a8628a）；保留其 2 条回归测试，后续巡检类豁免改造时显式引用 start_after_pending 场景防再次遗漏。

### 可改进
- **静态行号锚点三连漂移修复**
  - 影响：窗口内 3 次写点/锚点漂移修复提交（14380774、2e98e052、762b4aee），每次手工重钉 3-4 个行号；2e98e052 说明 relint-gate 合并插入 154 行后 test_cancel_holdstate_recovery 4/6 子用例红灯（回归暴露）；复发敞口=每个并行分支合并周期（窗口 91 commits/24h）。
  - 证据：14380774「verification.py 插入降档读写后，_cancelled_hold 写点行号整体后移（1431/1742/2515 → 1451/1781/2560）」；2e98e052「relint-gate 合并…在 dispatch.py 三处挂点、verification.py 尾部一处挂点共插入 154 行…（1005/1841/2299/2560 → 1028/1912/2391/2611）…4/6 子用例红灯」；762b4aee「内容闸门…各插入 14/13 行…后移 27 行（1028/1912/2391 → 1055/1939/2418）」。
  - 调查评估：已核实三 commit 均为 WRITE_POINTS/行号静态钉点的行号重钉、无语义改动，且 2e98e052 还带出真实红灯回归。根因=测试断言与被测代码以绝对行号耦合，在高频并行合并下必然失配，每次靠人工重钉。检索 spec/changes 与 spec/archive 未见行号锚点专项 → 新立项方向。结论=系统性缺口，值得 SPEC 立项。
  - 建议：立项将取消/写点断言改为语义锚点（函数名/最近唯一模式串 + 相对偏移），并在 post-merge 增加锚点自检（合并后自动重算、失配即红测试提示），消除手工行号对齐。

- **run 延迟观测全盲 30 连发**
  - 影响：窗口内全部 30 个 run 完成时 latency_rounds=0 / latency_stalls=0 / latency_p90=null，依赖该口径的秒挂/停滞检测与 add-turn-limit-anchor-c 锚点 C 的 unobserved 续期判定基于空数据运行；复发敞口=每次 run 均无延迟证据，秒挂=0 与超时=0 统计可信度存疑。
  - 证据：fenixd.log 每条 run 完成均报「0 rounds（无 timestamp 样本，旧转录跳过）」（如 3373 行 run impl-add-main-tree-deps-provision-1789132993 latency_p90=null）；但同 run 转录 .fenix/runs/impl-add-turn-limit-anchor-c-1789107200-a1.jsonl 实际 181/288 条 assistant 行含 ISO timestamp（如 2026-09-11T06:13:50.042Z）。
  - 调查评估：已核实转录含 timestamp 而解析器报无样本，判定延迟解析器与当前 stream-json 转录格式失配（「旧转录跳过」）。根因=转录格式更新后解析器未同步。add-turn-limit-anchor-c 的 ANCHOR_TURN_LIMIT / 续期矩阵 / unobserved 口径直接消费该观测 → 护栏失效波及锚点判定。窗口内未见修复。结论=观测基础设施空缺，值得小 SPEC 修复并加自检。
  - 建议：修复 run 延迟解析器对当前转录 timestamp 的兼容（重建 rounds/timestamp 映射），并加「latency_rounds>0」观测自检：若持续为 0 则显式告警，避免静默盲区。

- **两簇存量测试失败拖累回归**
  - 影响：修复前，5 例 daemon_lifecycle + 18 例 verify 系失败属存量（import fenixd 包截胡可溯源 08-16 迁移遗留，已 26 天），期间任何全量回归须先甄别 23 个非当前改动失败才能判新回归，污染每轮解释；15:19 修复后全量 2651 passed。
  - 证据：d4978dbf（09-11 15:19）「修复全量回归两簇存量失败（import fenixd 包截胡 + verify_engine reload 换类污染）…全量 2651 passed」；正文列根因：仓库根 __init__.py（08-16 迁移遗留 51B 纯注释）使 pytest 执行期 import fenixd 撞包；test_planready_artifact_gate 未 patch importlib.reload 触发 TestScenario 类热换。
  - 调查评估：已核实 commit 内容：两簇根因均为测试基座缺陷而非产品缺陷，窗口内已修复并 2651 passed 验证。根因=测试基础设施无自洽清理（import 守卫缺失）+ reload 副作用未隔离，且存量失败长期无独立追踪渠道（未见 known-failures 清单）。与在飞 SPEC 无重叠。结论=一次性清理完成，建议补回归锚点防回退。
  - 建议：新增两条回归锚点：① 仓库根 __init__.py 保持空或禁包，import fenixd 用 sys.modules 断言守卫；② test_planready_artifact_gate 补 importlib.reload patch，避免同簇失败 26 天后再现。
