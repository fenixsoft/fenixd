# 验证报告：fix-fixture-project-alert-noise

> ⚠️ 本报告由框架于 2026-09-18T20:21:42Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T20:21:42.405864+00:00

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.43M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| reset-marks-fixture-in-registry | 正向路径·夹具供给脚本登记契约（Requirement: 夹具供给脚本复位告警基线并标记夹具——复位确保夹具标记就位）：执行 bin/fixture_scheduling_showcase.py --reset 后，全局注册表 ~/.config/fenixd/dashboard.yaml 中 scheduling-showcase 条目被标记 fixture: true（add_project(ROOT, fixture=True) 或 mark_fixture 补写），Registry.discover() 返回其 fixture=True，未标记项目（fenixd）fixture 恒为假；复位同时把夹具 .fenix/admin_alerts.json 收为空基线 []。出处：bin/fixture_scheduling_showcase.py:66-88（_ensure_registered：add_project(fixture=True) → 已存在则 mark_fixture 补写）、registry.py:143-224（discover fixture 透出）、registry.py:228-265（add_project fixture 参数）、registry.py:267-294（mark_fixture） | pass | 0/7 | - |
| fixture-governance-pytest-suite | 回归点·实现侧单元测试套件全绿（覆盖 Requirement 1/2/3/4 全部 spec 场景的 Python 级断言，含「非夹具项目告警不受影响」构造——fixture:true 与 fixture:false 双项目并存、非夹具告警进 alerts 与 total_unhandled）：python3 -m pytest tests/test_fixture_project_governance.py -q 18 项全部通过。出处：tests/test_fixture_project_governance.py:63-433（TestDiscoverFixtureFlag/TestAddProjectAndMarkFixture/TestAlertsAggregationFilter/TestAdminActivitiesAggregationFilter/TestResetAlertsBaseline/TestFixtureVisibility 六个测试类 18 个用例） | pass | 0/2 | - |
| registry-add-project-writes-fixture-flag | 正向路径·Registry.add_project 写入夹具标记（Requirement: 夹具项目标识的读写与透出——add_project 支持 fixture 参数）：以临时 dashboard.yaml 构造 Registry，调用 add_project(path, fixture=True) 注册临时 Fenixd 项目，配置 projects 条目含 fixture: true 且 discover() 返回的该项目 dict 含 fixture: true。出处：registry.py:228-265（add_project 写入 {"name","path","fixture"}）、registry.py:174-181（discover 显式条目 fixture 透出） | pass | 0/4 | - |
| registry-mark-fixture-updates-existing-entry | 正向+异常路径·Registry.mark_fixture 补写存量条目标记（Requirement: 夹具项目标识的读写与透出——存量条目补写夹具标记）：对已存在但无 fixture 键的配置条目调用 mark_fixture(path, fixture=True) 写入 fixture: true 且 discover() 透出；对不在配置中的路径调用 mark_fixture 返回未变更提示且不抛异常（返回 updated=False）。出处：registry.py:267-294（mark_fixture：按规范化路径定位写入后写回，缺条目返回「项目未在监控列表」不抛异常） | pass | 0/6 | - |
| registry-unmarked-and-scanned-default-false | 缺省路径·未配置 fixture 键的显式项目与扫描发现项目 fixture 缺省为假（Requirement: 夹具项目标识的读写与透出——未标记与自动扫描项目缺省非夹具）：临时注册表扫描根下构造含 .fenix/STATE.md 的被扫描项目 + 无 fixture 键的显式项目，discover() 结果两者 fixture 均为 False（扫描无法判定夹具属性，缺省保守=非夹具）。出处：registry.py:180（显式条目 p.get("fixture") is True）、registry.py:214-222（扫描发现项目恒 fixture=False） | pass | 0/4 | - |
| fixture-project-still-visible-in-overview | 回归点·fixture 标记不影响项目可见性（Requirement: 夹具项目标识的读写与透出——夹具标记不影响项目可见性）：GET /api/overview 跨项目概览仍返回该夹具项目卡片（scheduling-showcase 出现在 projects 数组）——过滤面收窄在告警/运维记录两个聚合端点，项目列表/overview 不隐藏夹具。出处：core/dashboard/routes/project_routes.py:48-49（_api_overview 走 self.server.projects() 全量，MUST NOT 加夹具过滤）、core/dashboard/data/summary.py:837-856（overview 逐项目聚合，仅过滤 exists 不辨 fixture）、路由注册 core/dashboard/routes/base.py:262（/api/overview [GET]） | pass | 0/3 | - |
| seed-fixture-alert-disposition-resolved | 数据准备·向夹具写入验证数据（供 api/web 场景消费；本轮 prepare 的 --reset 已清空基线，seed 恢复确定性状态）：经真实 AdminStore.append 向 /root/scheduling-showcase/.fenix/admin_alerts.json 写入 3 条真实形态记录——未处理升级告警（kind=escalation、handled=false、severity=major）、已解决升级告警（handled=true、handled_by=auto-resolve、resolve_note）、处置记录（kind=disposition、admin_run_id）。写侧 seed 场景保持既有真实形态（spec 非目标：不改写侧）。出处：core/admin_store.py:227-234（append 真实写路径）、core/admin_store.py:202-225（_normalize_entry 补齐 id/created/handled）、core/admin_store.py:58-59（admin_alerts.json 存储路径） | pass | 0/7 | - |
| alerts-aggregate-skips-fixture-project | 正向路径·/api/alerts 缺省（跨项目聚合）分支跳过夹具项目（Requirement: 跨项目告警聚合跳过夹具项目——缺省聚合不出现夹具项目告警）：夹具含未处理 major 升级告警与已解决告警时，GET /api/alerts（不带 project 参数）响应的 alerts/resolved/projects 中均不含 scheduling-showcase 条目（无夹具 spec/id 泄漏），total_unhandled 字段存在且非夹具项目（fenixd）照常聚合。出处：core/dashboard/routes/alert_routes.py:45-47（_api_alerts 缺省分支 if p.get("fixture"): continue）、路由注册 core/dashboard/routes/base.py:268（/api/alerts [GET]）（judge 修复 remove_reason：移除两条语义写反的 body_contains——body_contains=正包含而 label 意图为「夹具 spec 不出现在响应体」，产品正确时必失败；等效验证已由 json_schema not.contains 覆盖且通过；json_path projects.0.name 修正为 projects[0].name 数组下标语法） | pass | 0/4 | - |
| alerts-explicit-query-returns-fixture-records | 回归点·/api/alerts 显式查询分支保留夹具记录（Requirement: 跨项目告警聚合跳过夹具项目——显式查询夹具项目仍返回记录）：GET /api/alerts?project=scheduling-showcase 返回项目全部告警/处置记录与摘要——摘要 unhandled_count=1（仅未处理升级告警）、max_severity=major，alerts 含 seed 的未处理/已解决/处置三条记录原文（spec/evidence 逐字保留）。出处：core/dashboard/routes/alert_routes.py:29-39（显式分支 project_by_name 直读，MUST NOT 改动）、路由注册 core/dashboard/routes/base.py:268 | pass | 0/9 | - |
| admin-activities-aggregate-skips-fixture-project | 正向路径·/api/admin-activities 缺省（跨项目聚合）分支跳过夹具项目（Requirement: 跨项目运维记录聚合跳过夹具项目——缺省聚合不出现夹具项目处置记录）：夹具含 seed 处置记录时，GET /api/admin-activities（不带 project 参数）响应的 projects 数组不含 scheduling-showcase 分组，非夹具项目（fenixd）照常出现。出处：core/dashboard/routes/alert_routes.py:95-97（_api_admin_activities 缺省分支 if p.get("fixture"): continue）、路由注册 core/dashboard/routes/base.py:271（/api/admin-activities [GET]）（judge 修复 remove_reason：移除语义写反的 body_contains fixture-seed-dsp-governance（正包含 vs 意图不存在，产品正确必失败；由 json_schema not.contains 等效覆盖）；json_path 修正为 projects[0].name） | pass | 0/4 | - |
| admin-activities-explicit-query-returns-fixture-records | 回归点·/api/admin-activities 显式查询分支保留夹具处置记录（Requirement: 跨项目运维记录聚合跳过夹具项目——显式查询夹具项目处置记录仍返回）：GET /api/admin-activities?project=scheduling-showcase 返回该项目的处置活动列表，activities 含 seed 的 disposition 记录（spec/evidence/admin_run_id 逐字保留）。出处：core/dashboard/routes/alert_routes.py:81-92（显式分支 project_by_name 直读，MUST NOT 改动）、路由注册 core/dashboard/routes/base.py:271 | pass | 0/7 | - |
| overview-banner-hides-fixture-alert-card-visible | 端到端·用户视野不出现夹具告警横幅 + 夹具卡片仍可见（核心用户故事回归：用户不定时收到夹具项目人工升级告警横幅——修复后跨项目聚合跳过夹具，顶部告警横幅不再渲染夹具 seed 告警；同时夹具项目卡片仍显示在项目清单，用户仍可进入查看）：夹具含 seed 未处理/已解决告警时打开概览页，.ant-alert 告警横幅区域不含夹具 seed 的 spec 文本、.overview-project-card 项目清单仍含 scheduling-showcase 卡片。导航出处：#/overview hash 路由——core/dashboard/static/src/app.tsx:52（顶栏 home 面包屑 href="#/overview"）、app.tsx:101（菜单 path "/overview" 概览页）；AlertBanner 挂载于概览页 core/dashboard/static/src/pages/overview/index.tsx:69（<AlertBanner refreshTick>，内部 antd <Alert banner> 渲染 .ant-alert、展开列表 AlertLines 渲染 item.spec）；ProjectCards 容器 .overview-project-card core/dashboard/static/src/pages/overview/components/ProjectCards.tsx:163 | pass | 0/6 | - |
| reset-clears-alerts-baseline-idempotent | 正向+幂等·夹具供给脚本 --reset 复位告警基线并保证幂等（Requirement: 夹具供给脚本复位告警基线并标记夹具——复位清除上一轮 seed 告警/复位确保夹具标记就位/复位幂等）：先向夹具写入 seed 告警模拟上一轮污染，执行 --reset 后 .fenix/admin_alerts.json 复位为空基线 []（读写层 AdminStore.read_all() 返回空集）、--status 显示 registered: True 与 alerts 0 records、registry 中夹具条目仍 fixture: true 且仅一条；连续两次 --reset 状态一致（第二次后仍为空基线、不产生重复项目条目）。出处：bin/fixture_scheduling_showcase.py:128-161（_reset_alerts_baseline 原子写 []）、:164-174（_alerts_count 供 --status）、:176-210（reset_fixture 基线写回 + _ensure_registered）、:213-230（show_status 输出 registered/alerts） | pass | 0/14 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

