# 验证报告：improve-spec-topology-pipeline-view

> ⚠️ 本报告由框架于 2026-10-26T04:41:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-26T04:35:55.369931+00:00+run-result@mtime1792989683087858547

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 15/18 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

18 场景：15 pass / 2 warning / 1 failed。唯一产品缺陷：管线视图生命周期链长状态名标签被 midTrunc(…,10) 中段截断（implementing→imple…ting），违反 →<目标状态> 完整标签契约，判 product-bug/major。两个 warning 均为截图健全性 low_contrast 环境性伪画面致基线顺延（功能断言全过，含优先复核场景 pipeline-hover-card-regression 经跨轮指纹复用维持 env/warning，平行上下文 batch=1、peers 17、observed_parallel=1）。静态情报双Han选择器两项（交付/用户）均为误报：目标为 SVG 文本/容器而非 antd Button 且断言实际通过，无需修复场景文件。

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 0.65M |
| 本链增量 Token（输出） | 0.14M |


## 真实产品 Bug

### BUG-01（severity=major）· element_visible

- 关联场景：pipeline-lifecycle-chain-nodes
- 描述：管线视图生命周期链节点标签对长状态名做中段截断：「implementing」渲染为「→imple…ting」、「implemented」渲染为「→imple…nted」，与「implemented」截形前缀难辨，用户无法从链上读出完整目标状态，违反 design D5「标签 →<目标状态>」契约
- 根因：PipelineView.tsx:387 对生命周期链转移标签套用 →{midTrunc(tr.to, 10)}（shared.ts:80 中段截断，保留头 5+尾 4 字符）；该截断工具本为 run_id/摘要设计，状态名全词可辨识性被破坏，12 字状态名恒失配完整文本
- 证据（场景 pipeline-lifecycle-chain-nodes 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": "svg text:has-text(\"→implementing\")", "expected": "implementing 转移节点可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded（等待 .first 可见）"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/improve-spec-topology-pipeline-view/screenshots/pipeline-lifecycle-chain-nodes_assert_fail_0.png"]
  - first_failed_step: 断言2（implementing 转移节点可见）：svg text:has-text("→implementing") 3s 超时——PipelineView.tsx:387 midTrunc(tr.to,10) 将标签截成「→imple…ting」


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| run-id-spec-review-attribution-suite | 数据单源·spec-review uuid 段剥除回归套件：运行交付测试 tests/test_run_id_spec_review_attribution.py（pytest -v，不并写 -q 以保 PASSED 行输出形态），覆盖任务 1.1/1.2——spec-review 形态（spec-review-<spec>-<6hex>-<ts>，含 -a/-r 多段后缀组合）剥除后与真实 spec 名全等；非 spec-review 形态（9-10 位数字尾、fix 家族递归前缀、impl/planner 前缀）快照零回归。exit 0 + 汇总 passed 即 D1 单源修复达标。出处：spec/changes/improve-spec-topology-pipeline-view/tasks.md:28-35、specs/topology-derivation/spec.md「spec-review run 归属（uuid 段剥除）」Requirement、core/agent_runner/run_files.py:184（run_spec_part 全仓归属单源） | pass | 0/4 | - |
| run-spec-part-boundary-probe | 边界形态直探·run_spec_part 单源函数契约：不经测试文件直接 import 生产函数，对 10 个边界 run_id 形态断言返回值——spec-review 三态（标准 6hex uuid 段、带 -a2 attempt 尾、无 uuid 段）剥除后全等；非 spec-review 形态与修复前逐例一致：impl -a2→foo、impl -a1-r2→foo、planner-plan→foo、fix-fix-foo-<ts>→fix-fix-foo（fix 前缀不剥，family 正则消费）、spec 名以 9/10 位数字结尾被既有时间戳剥离限制误剥为 spec（code-review 6c089e65a080 已记录行为，本任务不得改变）。exit 0 + RSPPROBE-OK。出处：tasks.md:28-32、core/agent_runner/run_files.py:184-206（时间戳剥离 9-10 位限定注释）、core/dashboard/data/topology.py:307（_family_run_paths 全等预过滤消费方） | pass | 0/2 | - |
| logger-event-size-cap-suite | 写侧治理·单事件序列化体积上限回归套件：运行交付测试 tests/test_logger_event_size_cap.py（pytest -v），覆盖任务 1.3/1.4——巨型 context（实测样本形态：admin_monitor 信号嵌入 51054 个untracked entry 单行 6.6MB）截断后落盘单行 ≤ LOG_EVENT_MAX_BYTES（256KB）且仍为合法 JSONL、含 truncated 标记与 message 完整；正常事件序列化结果与截断逻辑接入前逐字节一致。出处：tasks.md:36-42、specs/daemon-log-event-governance/spec.md「日志写侧单事件序列化体积上限」两 Scenario、core/logger.py:41（json.dumps 序列化出口） | pass | 0/4 | - |
| logger-cap-live-probe | 写侧直探·JsonFormatter 截断防御契约：不经测试文件直接构造 LogRecord 驱动生产序列化出口——300KB context 经 format 后单行 ≤ LOG_EVENT_MAX_BYTES+2KB 开销、无内嵌换行（合法 JSONL 单行）、context 替换为 {truncated:true, orig_bytes:int, context_keys 含 blob} 占位摘要、message 完整保留；对照组常规小 context 事件原样序列化（无 truncated 标记、context 逐字段保留、message 不变）。出处：specs/daemon-log-event-governance/spec.md 写侧两 Scenario、design.md D3（占位摘要 schema）、tasks.md:36-39 | pass | 0/2 | - |
| log-index-giant-line-suite | 读侧治理·锚定窗口超长行防御回归套件：运行扩展后的 tests/test_dashboard_log_index.py（pytest -v），覆盖任务 1.5/1.6——首行 6.6MB 巨型行日志 fixture 下 created 锚点在巨型行之后时窗口含锚点后可解析事件、单请求读取字节数有界（不以窗口上限整读巨型行）、常规日志（无超长行）窗口起点/终点/截断标记与既有行为一致。出处：tasks.md:43-51、specs/daemon-log-event-governance/spec.md「日志读侧锚定窗口跳过超长行」三 Scenario、core/dashboard/data/log_index.py:384（_read_log_window_from）、:421（_first_ts 块首行探测） | pass | 0/3 | - |
| log-window-giant-line-probe | 读侧直探·巨型行日志窗口行为（临时目录夹具，不读主树 .fenix/）：构造首行 300KB 巨型行+两条后续事件的合成日志，锚点（11:00）落在巨型行（10:00）之后——read_log_window_from 返回窗口必须含锚点后两条可解析事件（hello-one/hello-two）、不含巨型行载荷（GGGGG 被 seek 越过不进窗口）、truncated=False（文件<1MB 窗口上限）；对照组常规日志同锚点窗口与原始文件字节全等（同起点同终点截断语义不变）。出处：specs/daemon-log-event-governance/spec.md 读侧 Scenario 1/3、design.md D2、tasks.md:43-51 | pass | 0/2 | - |
| topology-derivation-suite | 派生层·串行判定与 dispatch 锚点回归套件：运行扩展后的 tests/test_topology_derivation.py（pytest -v），覆盖任务 2.1-2.3——handoff 单一串行判定（prev.end ≤ cur.start 且 prev.start < cur.start 才画边；同刻启动/时间重叠一律无边、双零时长退化不判串行；串行贴邻照画；attempt retry 边与 dispatch 边不受影响）、run 首节点 dispatch_anchor 区间归位（tr:<n>）与无法定位回退缺省，临时目录夹具不读主树 .fenix/。出处：tasks.md:55-66、specs/topology-bigscreen-ui/spec.md「并行无伪串行边」Requirement 两 Scenario、core/dashboard/data/topology.py:521-527（现伪 handoff 边构建处） | pass | 0/3 | - |
| topology-endpoint-spec-review-node-restored | 正向路径·spec-review 节点恢复上端点：GET /api/specs/add-collab-graph-bigscreen/topology?project=fenixd（实测样本 SPEC：archive 内存有 spec-review-add-collab-graph-bigscreen-8e869d-1792938331.jsonl 产物，修复前 uuid 尾巴致 family 全等预过滤失败、节点整体丢失）——修复后 run_spec_part 全等归属恢复，nodes[2]（user/pm 之后的最早 run 节点，其 started 14:26:05Z 早于 impl/planner-plan 14:32:58Z）为 kind=run、agent_type=spec-review、stage=demand 的需求评审节点，响应体含该 run_id 全串。出处：specs/topology-derivation/spec.md「拓扑含需求评审节点」Scenario、core/pm_engine/spec_review.py:392（run_id 形态单源写入点）、core/dashboard/routes/base.py:722（端点路由） | pass | 0/7 | - |
| topology-endpoint-transitions-completeness | 数据完整性·transitions 不再因巨型行归零：同端点同 SPEC——daemon 日志首行 6.6MB 巨型行仍占文件头（.fenix/logs/fenixd.log 实测首行 6668487 字节），读侧跳行修复后锚定窗口覆盖锚点后可解析事件：transitions 首条为 drafted→reviewing（日志旧→新扫描序）、数组含 to=pushed 终态转移（minItems≥1+contains），且 run 首节点派发归位锚点字段 dispatch_anchor 已随节点下发（任务 2.2，transitions 存在时必可定位）。出处：specs/topology-derivation/spec.md「状态转移派生完整性」Scenario 1、tasks.md:59-63、design.md D5 | pass | 0/6 | - |
| topology-endpoint-pseudo-edge-eliminated | 边语义·同刻启动无边且串行链保留（端点数据层）：同端点 edges 数组双 schema 断言——不存在 from=run:impl-add-collab-graph-bigscreen-1792938778-a1 且 to=run:planner-plan-…-1792938778-a1 的边（两者 started 同为 2026-10-25T14:32:58Z，伪 handoff 必须消除、不分边型）；存在 from=run:planner-judge-…-1792941069-a1 且 to=run:planner-judge-…-1792942334-a1 的串行边（judge1 结束 15:29:11 ≤ judge2 开始 15:32:14，串行贴邻保留 handoff）。出处：specs/topology-bigscreen-ui/spec.md「并行无伪串行边」两 Scenario、tasks.md:55-58、core/dashboard/data/topology.py:521-527、实测样本 duration_seconds（judge1 1082s） | pass | 0/3 | - |
| topology-endpoint-archived-skeleton | 回归点·归档 SPEC 骨架不受超长行防御影响：对归档 SPEC add-fenix-dashboard（run 产物已随归档清理、日志窗口退化 transitions 恒空）调端点——200、archived=true、骨架节点集不变（nodes[0]=user、含 delivery 终点）、transitions 为空数组不异常。出处：specs/topology-derivation/spec.md「归档 SPEC 转移骨架不受影响」Scenario、tasks.md:77-78（任务 3.3 归档骨架） | pass | 0/3 | - |
| pipeline-parallel-alignment-time-axis | 正向路径·纵轴真实时间与并行水平对齐：直入样本 SPEC 拓扑大屏（路由 /projects/:name/:spec/topology，layout:false 脱壳）切管线视图——开发列 implementer 与规划列 planner-plan 同刻启动（2026-10-25T14:32:58Z），两节点标签文本顶边纵坐标差 ≤3px（alignment axis=top），并行结构水平对齐可读；数据修复恢复的「需求评审 Agent」节点在场；svg 文本含 fmtTick「MM/DD HH:MM」格式时间刻度（全链跨度 >2h 走日期+时刻档，复用协作时序档位与文案格式）。出处：specs/topology-bigscreen-ui/spec.md「管线视图七阶段列」Scenario 1、tasks.md:70-73（任务 3.1）、core/dashboard/static/config/routes.ts:38（路由）、SwimlaneView.tsx:37（fmtTick 档位复用源） | pass | 0/8 | - |
| pipeline-lifecycle-chain-nodes | 正向路径·PMEngine 生命周期节点链上屏：样本 SPEC transitions 修复后可派生（daemon 日志实测 8 条 Transition 行：drafted→reviewing→ready→implementing→implemented→testing→verified→done→pushed 语义链），管线视图逐条渲染为带 →<目标状态> 标签的小节点——svg 内含箭头标签的 text 叶节点恰 8 个、→implementing 与 →pushed 在场（链序与时序一致由 api 场景 transitions 数据与派生单测双背书）。出处：specs/topology-bigscreen-ui/spec.md ADDED「PMEngine 生命周期节点链」Scenario 1、design.md D5（标签 →<目标状态>、链置于 PMEngine 节点处）、tasks.md:74-76 | failed（已修正） | 1/7 | product-bug |
| pipeline-serial-judge-chain | 正向路径·串行先后可读：6 轮 planner-judge（started 依次 15:11:09→15:32:14→15:55:40→16:06:38→16:26:16→16:39:09，实测样本）按纵轴真实时间渲染——「判定结果 Agent」标签叶节点恰 6 个、不被遮挡可直击（no_click_interception：时间映射后若节点叠置，命中测试必被后绘节点拦截；原 no_overlap 因引擎「.first vs 父 children」几何口径恒撞全高列背景组与边 path bbox，对本画布不可满足，已原地修复），先后顺序无需悬停即可从纵轴读出；纵坐标严格递增的数据层证据由 api 场景（时刻字段）与派生单测排序键双背书。出处：specs/topology-bigscreen-ui/spec.md「管线视图七阶段列」Scenario 2（串行先后可读）、tasks.md:70-73 | warning | 0/4 | env |
| pipeline-transitions-empty-degradation | 降级路径·transitions 为空与归档骨架不断链：对归档 SPEC add-fenix-dashboard（transitions 空、run 产物已随归档清理、user/pm 无可靠时刻）打开大屏管线视图——页面正常渲染无 NaN 坐标不抛错（退出大屏按钮与画布在场）、PMEngine 主节点与用户入口节点保留、无 → 生命周期链节点（element_not_exist）、无控制台错误。出处：specs/topology-bigscreen-ui/spec.md「transitions 为空不渲染链不断链」与「无时刻节点降级布局」两 Scenario、tasks.md:77-78（任务 3.3） | pass | 0/7 | - |
| pipeline-interactions-regression | 交互回归·布局重构后既有交互不回归：点击判定节点下钻运行记录弹窗（.ant-modal-title 含「运行记录」）→关闭弹窗→切协作时序→切回管线视图——往返后画布恢复且生命周期链仍在场（→pushed 可见），跨视图 selectedId 联动契约随选中保留。出处：tasks.md:79-81（任务 3.4：悬浮卡/点击下钻/跨视图 selectedId 联动不回归）、design.md D4（交互契约不变） | pass | 0/5 | - |
| pipeline-hover-card-regression | 交互回归·节点悬浮详情卡：悬浮（hover）判定节点后 HTML overlay 详情卡出现——卡内含「点击查看运行记录」引导行与「run_id：」字段行（角色/run_id/状态/LLM/耗时/成本/重试结构保留）。hover 为本场景最后一步，指针停驻期间断言。出处：tasks.md:79-81（任务 3.4 悬浮卡不回归）、design.md D4（悬浮卡契约不变）、PipelineView.tsx:253-289（现有卡结构） | warning | 0/3 | env |
| swimlane-lanes-recovery | 泳道自动恢复·需求评审泳道数据回流：切协作时序视图——八泳道行标签齐备（用户/PMEngine/需求评审/规划/开发/审查/修复/测试/验证/运维）、时间刻度轴在场、run 色块渲染（数据修复后含恢复的需求评审泳道数据）；泳道结构零重构（本 SPEC 不改泳道，仅数据回流自动恢复）。出处：proposal.md:35（泳道视图因数据修复自动恢复）、tasks.md Non-Goals（不重构泳道）、core/dashboard/static/src/pages/projects/topology/SwimlaneView.tsx（LANE_ORDER/LANE_LABELS） | pass | 0/7 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| pipeline-serial-judge-chain | visual baseline pipeline-serial-judge-chain（baseline_rejected/low_contrast） | env | 环境因素（非产品缺陷） | 功能断言全过（element_count 6/no_click_interception/element_visible/no_console_error 均过），唯一失败信号是截图健全性 low_contrast（pixel_std 0.0670）拒绝固化基线——环境性伪画面非产品缺陷；同窗并行 paralle... |
| pipeline-hover-card-regression | visual baseline pipeline-hover-card-regression（baseline_rejected/low_contrast） | env | 环境因素（非产品缺陷） | 功能断言全过（悬浮卡出现/run_id 字段在场/无控制台错误），唯一失败信号是截图健全性 low_contrast 拒绝固化基线——环境性伪画面非产品缺陷；同窗并行上下文 parallel_context：batch=1、peers 17 场景、observed_parallel=1，基线顺延不阻塞 |

## 本轮场景集变更

场景集与持久化集一致，无变更。

