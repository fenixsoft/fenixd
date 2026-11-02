# 验证报告：evo-code-review-snapshot-writeoff-integrity

> ⚠️ 本报告由框架于 2026-10-30T14:39:21Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T14:39:20.509616+00:00+run-result@mtime1793371160599447936

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.88M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| crsnap-seed-verify-projects | 夹具供给（R4 dashboard 消费口径的前置数据面）：创建两个探针夹具项目 /tmp/fenix-verify-crsnap-a（台账 4 行：resolved+resolution=code-fix-auto、resolved+resolution=snapshot_closed、resolved 无 resolution 存量行、open 1 行）与 /tmp/fenix-verify-crsnap-b（台账仅 1 行 open），均以 Registry.add_project(fixture=True) 登记进验证实例注册表，轮询等待实例发现（容忍 projects 10s TTL 缓存）并确认 /api/code-review/items 端点按 status 过滤返回夹具行。出处：core/dashboard/registry.py:476（add_project fixture 标记）、core/dashboard/routes/code_review_routes.py:227-285（items 端点）、core/dashboard/data/code_review.py:52-92（读侧投影）夹具注册幂等：已登记路径按 registry.py:522 跳过语义视作注册成功，并经 registry.py:562 mark_fixture 补写 fixture 标记（跨轮复验不因上轮持久化而假失败）。 | pass | 0/5 | - |
| crsnap-pytest-snapshot-resolution-suite | R1/R5 交付测试套件全量回归：运行本 SPEC 新增的 tests/test_review_snapshot_resolution.py 全部 19 用例（-v），覆盖同缺陷措辞漂移对账迁移保持 open、迁移去重孪生合并、1:1 领用、并列 tie-break、孪生非 open 放弃迁移、真消失核销带 snapshot_closed、低相似度不误保、跨文件不对账、返回形态、无指纹条目保持 open。出处：tasks.md 3.1、tests/test_review_snapshot_resolution.py:103-352（TestDriftReconciliation 10 用例） | pass | 0/12 | - |
| crsnap-pytest-endtoend-run-counts-split | R2 观测记录传递 + R3 完成行分列的套件回归：运行 TestEndToEndDriftRun（run_code_review 收尾按 findings 同口径现算观测记录集传入 resolve_snapshot，漂移轮迁移后 snapshot_closed=0；真消失轮拆分计数）与 TestWriteoffCountsSplit（CodeReviewResult 携带 snapshot_closed/fixed 两字段、完成行 note 分列、admin_monitor 完成行格式）。出处：core/agent_runner/maintenance_runs.py:2612-2630（观测集现算与两计数装配）、core/agent_runner/result_gate.py:367-401（CodeReviewResult 分列字段）、core/admin_monitor.py:1598-1611（code_review_writeoff_counts_note）、:2218-2231（完成行输出） | pass | 0/7 | - |
| crsnap-pytest-codefix-scope-and-projection | R4 消费口径分列的套件回归：运行 TestCodeFixCountsUnaffected（snapshot_closed 核销不得改变 code_fix 进度 done 与 chain_rollup 计数、fresh 项目核销不产生 fix progress——tasks.md 2.2 不改码以测试锁定）与 TestDashboardResolutionProjection（dashboard 投影透出 resolution 字段、存量 resolution=None 按 snapshot_closed 口径解读不回填）。出处：core/code_fix.py:5929/:7484/:7489（rollup/done 由 mark_resolved 累积）、core/dashboard/data/code_review.py:66-71（resolution 随行透传注释） | pass | 0/6 | - |
| crsnap-pytest-legacy-signature-migration | 任务 3.2 既有用例迁移回归：运行 tests/test_code_review.py::TestSnapshotResolution（指纹集合入参用例迁移至观测记录集新签名，语义等价——命中保持 open、未观测核销带 snapshot_closed 标记；in_spec/ignored 不被快照核销触碰）。出处：tasks.md 3.2、tests/test_code_review.py:220-258 | pass | 0/4 | - |
| crsnap-pytest-combined-regression | 合并回归伞：两份台账测试文件（tests/test_review_snapshot_resolution.py + tests/test_code_review.py 共 165 用例）一次全量通过，锁定实现未破坏既有 code-review 台账行为。出处：tasks.md Deliverables（tests/test_code_review.py modify / tests/test_review_snapshot_resolution.py new） | pass | 0/2 | - |
| crsnap-live-resolve-reconcile-twin-merge | R1 独立功能验证·漂移对账与孪生合并（不经交付测试套件、直驱 core.code_review.resolve_snapshot）：夹具台账含旧措辞 open 条目（旧指纹）与本轮 upsert 语义插入的新指纹 open 孪生，以新措辞观测记录调用后——旧条目保持 open、指纹迁移为新指纹、item_id/first_seen_at 稳定、展示字段（title/description/review_id）随观测刷新、孪生被删除、台账同指纹仅一条、返回 {'snapshot_closed':0,'fixed':0}。出处：core/code_review.py:1100-1307（resolve_snapshot 对账/迁移/孪生合并）、:1259-1288（孪生合并分支） | pass | 0/9 | - |
| crsnap-live-resolve-claim-and-tiebreak | R1 独立功能验证·1:1 领用与并列 tie-break：两条未命中 open 条目争同一观测时仅相似度最高者迁移保持 open，另一条按未命中核销（resolution=snapshot_closed）；相似度并列时 last_seen_at 更近者领用迁移、更旧者核销；被领用观测不复用（返回计数恰 1 核销 1 迁移）。出处：core/code_review.py:1218-1250（贪心领用排序与 used_obs 复用拦截） | pass | 0/8 | - |
| crsnap-live-resolve-writeoff-safety | R5 安全边界独立验证：真消失条目（无任何相似观测）正常核销且 resolution=snapshot_closed、resolved_at 落值、last_seen_at 保持不动；相似度低于阈值 0.55 的同文件同类目条目不误保（按未命中核销）；同标题跨文件（对账分组键不符）不迁移、正常核销；in_spec/ignored 条目不被快照核销触碰；fingerprint 缺失的 open 条目跳过核销保持 open；裸指纹字符串观测形态兼容（命中条目保持 open）且返回恒为 {'snapshot_closed': n, 'fixed': 0} 字典。出处：core/code_review.py:1291-1296（未命中核销写标记）、:1227-1233（file+category 分组键）、:1236-1240（阈值判定）、:1135-1139（in_spec/ignored 与无指纹守卫） | pass | 0/11 | - |
| crsnap-live-completion-line-note-split | R3 完成行分列独立验证（直驱 core.admin_monitor.code_review_writeoff_counts_note 纯函数）：携带 snapshot_closed=3/fixed=0 的 CodeReviewResult 输出恰为 'snapshot_closed=3, fixed=0'；resolved 兼容别名恒等于 snapshot_closed；无分列字段的旧结果对象（daemon 旧码在飞形态）按 0/0 兜底不炸完成行。出处：core/admin_monitor.py:1598-1611（格式单源 f'snapshot_closed={closed}, fixed={fx}'）、core/agent_runner/result_gate.py:367-401 | pass | 0/5 | - |
| crsnap-live-projection-passthrough-no-backfill | R4 读侧投影独立验证（直驱 core.dashboard.data.code_review.read_code_review_items 消费 crsnap-seed-verify-projects 供数的 crsnap-a 台账）：statuses=['resolved'] 过滤返回 3 行且 resolution 分别为 code-fix-auto/snapshot_closed/缺失（存量行不回填）；缺省视图仅回 open 1 行；读后台账原始 jsonl 保持不变（cr-res-legacy 行仍无 resolution 键、resolution 键全文件恰出现 2 次——读侧零改写）。出处：core/dashboard/data/code_review.py:52-92、core/code_review.py:500-508（read_items 只读） | pass | 0/8 | - |
| crsnap-api-items-resolution-passthrough | R4 端点投影验收：GET /api/code-review/items?project=crsnap-a&status=resolved 返回 total=3 且三行 resolution 按严重度排序透传（critical 行=code-fix-auto、major 行=snapshot_closed、minor 存量行 status=resolved 且 item_id=cr-res-legacy）；缺省无 status 视图仅回 open 1 行（cr-open-show，锁住 wanted={'open'} 缺省行为不被破坏）；severity=major 过滤后仅 snapshot_closed 行。navigate 端点出处：core/dashboard/routes/base.py:685（/api/code-review/items [GET]）、core/dashboard/routes/code_review_routes.py:227-285 | pass | 0/15 | - |
| crsnap-web-qualitytab-resolved-badges | R4 dashboard 展示分列（桌面）：项目详情页切「代码审查」分面（点击触发台账拉取），缺省 open 视图仅显示未处置锚点行；状态下拉含来源中立选项「resolved（已核销）」，选后表格三行 resolved 按来源徽标分列（快照关闭×2——显式 snapshot_closed 与存量无 resolution 行、已修复×1——code-fix-auto 行），本页分列统计行显示「本页 resolved 共 3 条：已修复（合回核销） 1 · 快照关闭 2」。navigate 出处：core/dashboard/static/config/config.ts:32（history hash 路由）+ core/dashboard/static/config/routes.ts:48（/projects/:name）+ core/dashboard/static/src/app.tsx:132（菜单路径拼装）；分面挂载出处 core/dashboard/static/src/pages/projects/list.tsx:1582-1588；徽标出处 QualityTab.tsx:137-144/:1152-1167；分列统计出处 QualityTab.tsx:1294-1303；状态过滤选项出处 QualityTab.tsx:126-131 | pass | 0/13 | - |
| crsnap-web-qualitytab-mobile-badges | R4 dashboard 展示分列（移动端 390×844，<768 堆叠卡形态）：同一夹具项目在移动端 ProblemCellMobile 卡片上同样按来源徽标分列（快照关闭×2、已修复×1），状态过滤与分列统计行为与桌面一致。出处：core/dashboard/static/src/pages/projects/components/QualityTab.tsx:269-306（ProblemCellMobile 徽标行）、:313（useIsMobile 门控） | pass | 0/11 | - |
| crsnap-web-qualitytab-resolved-empty-state | 空状态回归（crsnap-b 台账仅 1 行 open、无 resolved）：状态下拉切 resolved（已核销）后表格空态文案为「暂无 resolved（已核销） 问题」（随过滤动态生成、沿用来源中立词表），且不渲染本页 resolved 分列统计行、无来源徽标残留。出处：core/dashboard/static/src/pages/projects/components/QualityTab.tsx:1386-1398（emptyText 动态生成）、:1297（无 resolved 行不渲染统计） | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

