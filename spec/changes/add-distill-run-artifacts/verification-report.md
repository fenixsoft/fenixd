# 验证报告：add-distill-run-artifacts

> ⚠️ 本报告由框架于 2026-11-01T09:13:47Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-01T09:13:46.504338+00:00+run-result@mtime1793524426556595331

## 结论：✅ 通过（verified）

**状态：verified — 19/19 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 19/19 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.75M |
| 本链增量 Token（输出） | 0.18M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| distill-batch-success-artifact | 蒸馏批次成功产物落盘：临时 git 项目内 fake spawn 写入合法知识树后直驱真实 DistillManager._run_batch，校验通过并提交，.fenix/runs/ 下出现恰一个 knowledge-distiller-<首归档名>-<Unix秒>.jsonl，首行为带 timestamp 与 archived 名单的开始事件行、末行 type=result，classify_run 判 done，一批=一个 run。出处：core/knowledge.py:1753（_run_batch 产物包装）、core/knowledge.py:1489（_distill_run_artifact_open）、specs/distill-run-artifacts/spec.md「批成功产物落盘」 | pass | 0/11 | - |
| distill-batch-error-terminal | 蒸馏 spawn 非零退出（网关拒识模型名形态）触发 _give_up：同批产物末行 type=error 且携带「非零退出」原因摘要，classify_run 判 error，todo.md 重试台账照常登记（观测 fail-open 不改蒸馏失败路径语义）。出处：core/knowledge.py:1836（spawn 失败 return 路径经 finally 收口）、specs「批失败写 error 终态」 | pass | 0/8 | - |
| distill-failopen-artifact-write | 产物写 fail-open 三道防线：append_run_line OSError 注入（开始/轮次行写失败）与 append_run_error OSError 注入（finally 终态行写失败）两种形态下，蒸馏 result/commit/pending 台账/todo 登记与无产物形态完全一致、无异常外泄。出处：core/knowledge.py:1516（OSError 吞掉返 None）、specs「产物写失败不阻断蒸馏」 | pass | 0/11 | - |
| distill-multi-archive-runid | 一批多归档：run_id 中段取首归档名（knowledge-distiller-<首归档名>-<ts>），开始行 archived 字段记录批内全名单，run_id 白名单允许归档目录名中的点号。出处：core/knowledge.py:1497（run_id 形态注记）、specs/distill-run-artifacts/spec.md「蒸馏批次产出 run 产物」、tasks 1.2 | pass | 0/7 | - |
| distill-fix-rounds-single-artifact | 多修正轮同产物：第一轮校验违规（rev 非整数）、第二轮修正通过，产物恰一个且行数随修正轮递增（started+round+round+result），末行终态 result、classify_run 判 done 不变。出处：core/knowledge.py:1806（_distill_run_artifact_round）、specs「文件行数随修正轮数递增但不改变终态判定」 | pass | 0/7 | - |
| distill-attribution-get-runs | get_runs 归属正确：done 终态蒸馏产物经 get_runs 返回 agent_type=knowledge-distiller、spec=剥前缀与时间戳段后的带日期前缀归档目录名、status=done。出处：core/agent_runner/run_files.py:108（前缀真源收录）、core/dashboard/data/runs.py:665（get_runs 行构造）、specs「get_runs 归属正确」 | pass | 0/8 | - |
| distill-admin-pm-lane-boundary | 消费面边界三侧锁定：admin_monitor._RUN_PREFIXES 不收录蒸馏前缀（error 蒸馏产物不还原活跃 spec 失败计数）；pm_engine 归属判定对与活跃 spec 同名单的蒸馏 run_id 不误命中（正向对照剥段名可命中）；_distill_lane_busy 在飞判定读队列+线程，蒸馏产物存在与否不改变返回值。出处：core/agent_runner/run_files.py:101（消费方核对注记）、fenixd.py:1937（_distill_lane_busy）、specs「不还原到活跃 spec 失败计数」「在飞判定不受产物影响」 | pass | 0/8 | - |
| distill-archive-filter-not-swallow | 归档剔除过滤不吞蒸馏 run + 成本缺失透传：STATE.archive.md 清单含首归档 SPEC 原始名（无日期前缀）且存在 done 终态蒸馏产物（spec 段=带日期前缀归档目录名），aggregate_org 全量窗运营线蒸馏卡 runs≥1（形态错位不命中剔除集），且无 usage 产物卡片 cost=None 不伪显 0。出处：core/dashboard/data/command_center.py:536（归档剔除过滤）、specs「归档剔除过滤不吞蒸馏 run」「成本缺失不伪显 0」 | pass | 0/8 | - |
| distill-pytest-artifact-suite | 本轮新增蒸馏产物单测全绿：pytest tests/test_knowledge_distill_run_artifacts.py（批成功/失败/修正轮/fail-open 两形态/批异常/多归档共 7 例）-v 全 PASSED。出处：tests/test_knowledge_distill_run_artifacts.py:41（TestDistillRunArtifacts）、tasks 1.2 | pass | 0/9 | - |
| distill-pytest-boundary-suite | 前缀边界与聚合出卡单测全绿：pytest TestKnowledgeDistillerPrefix（归属/剥段/admin 不还原/pm 不误命中/归档剔除不吞共 5 例）+ TestDistillerLaneAggregation（运营线出卡/零 run 空卡/无 usage 成本缺失/error 计入分母/三窗口共 5 例）-v 全 PASSED。出处：tests/test_run_spec_prefixed_attribution.py:334、tests/test_command_center_aggregation.py:1031、tasks 2.2/3.3 | pass | 0/12 | - |
| distill-regression-existing-suites | 既有套件回归零破坏：test_knowledge.py + test_command_center_aggregation.py + test_run_spec_prefixed_attribution.py 全量运行 exit 0 且汇总含 passed。出处：tasks 4.1 | pass | 0/2 | - |
| org-seed-distill-fixture | 播种验证夹具项目（/tmp 扫描根外临时路径，Registry.add_project 以 fixture=True 注册）：写入 done/error/昨日 done 三条蒸馏合成产物，并轮询 live 实例 /api/command-center/org?project=<夹具名> 直至夹具项目可聚合、打印蒸馏卡 JSON（供后续 api/web 场景依赖，规避 projects() 10s TTL 缓存）。出处：core/dashboard/registry.py:476（add_project fixture 标记）、core/dashboard/routes/command_center_routes.py:60（fixture 显式寻址聚合） | pass | 0/7 | - |
| org-seed-distill-empty-fixture | 播种零 run 夹具项目（fixture=True 注册，无任何蒸馏产物）并轮询至 live 实例聚合可见（运营线蒸馏卡 runs=0），供零 run 空卡场景依赖；与前序夹具播种串行避免注册表并发写。出处：core/dashboard/registry.py:476 | pass | 0/6 | - |
| org-api-distill-card-today | 蒸馏 run 入窗出卡（today 窗）：GET /api/command-center/org?project=distill-verify-fixture&window=today，运营线 zones[4].cards[2] 为 knowledge-distiller 卡：runs=2（1 done+1 error）、success_rate=0.5、status=idle、zone=运营线、window 回显 today。出处：core/dashboard/routes/command_center_routes.py:77（org 端点）、specs「蒸馏 run 入窗出卡」 | pass | 0/9 | - |
| org-api-distill-three-windows | 三窗口口径一致：同夹具 window=7d 与 window=all 两档请求的运营线蒸馏卡 runs 均=3（今日 2 + 昨日 1），window 字段回显各档值（今日 2 由 org-api-distill-card-today 覆盖）。出处：core/dashboard/data/command_center.py:486（aggregate_org 窗口语义）、specs「蒸馏 run 入窗出卡」三档口径一致 | pass | 0/8 | - |
| org-web-distill-card-ops-zone | 组织网格「知识蒸馏」卡中文标签与图标出卡：深链 /#/command-center?project=distill-verify-fixture&window=today，运营线分区出 knowledge-distiller 卡——主标题中文「知识蒸馏」（非英文 lane 原样）、副题 lane id、图标 BookOutlined（anticon-book，非 FileUnknownOutlined 兜底）、三格指标「今日实例数/今日成功率/今日成本」渲染。出处：core/dashboard/static/src/app.tsx:139（/command-center 路由）、shared.ts:173（LANE_LABELS）、OrgGrid.tsx:110（LANE_ICONS）、specs「中文标签与图标出卡」 | pass | 0/9 | - |
| org-web-distill-window-switch-refetch | 时间窗切换触发组织网格数据重拉取：点击页签右侧窗口下拉选「7 日」，该交互携带 expect_network 断言 /api/command-center/org 重拉取，卡片指标标签由「今日实例数」切换为「7 日实例数」。出处：core/dashboard/static/src/pages/command-center/index.tsx:173（窗口 Select）、shared.ts windowLabels（7 日标签） 修复注记：原两条 no_click_interception 断言在切窗完成后重放点击已态变选择器（选中值 title 变「7 日」/下拉已收起）恒败，属断言时序错置；已补展开下拉步骤并将下拉断言改为现态 title='7 日'。 | pass | 0/5 | - |
| org-api-distill-empty-roster-card | 零 run 编制内出卡：零 run 夹具 today 窗 org 响应运营线蒸馏卡 runs=0、status=idle（花名册编制内车道零 run 也出卡既有 Requirement 自动保证）。出处：core/dashboard/data/command_center.py:53（零 run 出卡注记）、specs「零 run 编制内出卡」 | pass | 0/7 | - |
| org-web-distill-empty-card-idle | 零 run 蒸馏卡空态：零 run 夹具深链组织网格 today 窗，运营线「知识蒸馏」卡出「空闲」状态徽标与「待命 · 等待信号」活动行。出处：OrgGrid.tsx:512（待命活动行）、shared.ts:66（空闲徽标）、specs「零 run 编制内出卡」 | pass | 0/5 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

