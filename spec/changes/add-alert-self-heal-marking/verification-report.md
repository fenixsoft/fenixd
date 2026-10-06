# 验证报告：add-alert-self-heal-marking

> ⚠️ 本报告由框架于 2026-10-06T10:09:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T10:09:01.472945+00:00+run-result@mtime1791281341511344792

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.47M |
| 本链增量 Token（输出） | 0.15M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-selfheal-registry-and-trigger-registration | 正向路径·覆盖族注册表与埋点登记（Requirement: 基础设施瞬态告警自愈闭环——注册表保守缺省不变）：SELF_HEAL_SIGNAL_TYPES 初始 MUST 含 daemon_errors / run_infra_failure / self-evolution（evo 分析 run 失败写入点 _evolution_warn 的 signal_type 常量，fenixd.py:4377）且 MUST NOT 含 env 握手族 inconclusive_loop（既有契约：其出口是人工裁决，保守缺省永不自动闭环）；CONDITION_INFRA_TRANSIENT_SELF_HEALED 条件常量在场；build_trigger/_SIGNAL_CONDITIONS 登记三族（daemon_errors 注册见 core/admin_monitor.py:290、run_infra_failure :369），使既有 attach_trigger 统一埋点写入点自动带 trigger，inconclusive_loop 仍返回 None。出处 core/alert_lifecycle.py:66-71（既有枚举与保守缺省注释）、:74-87（build_trigger）、fenixd.py:4367-4377、spec.md ADDED「注册表外 signal_type 永不自愈闭环」 | pass | 0/7 | - |
| cli-selfheal-store-auto-self-heal-writeback | 正向路径＋异常路径·AdminStore.auto_self_heal 写回契约（design D3、tasks 2.1）：临时工程根经 AdminStore.append 播种 escalation（收敛升级、带 admin_run_id）/ signal（run_infra_failure）/ 人工已 handled escalation / disposition 四条，auto_self_heal 下发三条 resolutions——escalation 与 signal 双 kind 均被关闭：handled=True、handled_by=auto-self-heal、handled_at 在场、resolve_note 以「已自愈：」前缀；人工 handled=True 条目跳过、字段逐位不变（人工记录不可覆盖）；同根 disposition 记录本体逐位不变（AdminMonitor 生效核查 fail-closed 契约不破，自愈只收口人工甄别面）；空 resolutions 零写回（文件 mtime 不变）。写回在排他锁内单次读-改-写，实现模式对齐既有 auto_resolve（core/admin_store.py:680）。出处 core/admin_store.py:32-33（ESCALATION/SIGNAL 常量）、design.md D3、spec.md「收敛升级收口不触碰处置台账」「人工处理记录不可覆盖」场景 | pass | 0/11 | - |
| cli-selfheal-deliverable-test-suite | 交付物测试套件全绿（tasks 1.4/2.2/3.2/4.2/5.3 的用例载体）：pytest 运行交付物新测试文件 tests/test_alert_self_heal.py（Deliverables kind: new）全量通过——覆盖六组规定用例：安静超窗闭环 / 窗口内复现保持 / env 握手族排除 / spec 附着族不双重判定 / handled 不覆盖 / 回填推断，外加 signal 与 escalation 写回、disposition 逐位不变、配置兜底、埋点断言、数据层映射。命令只用 -v（禁与 -q 并列：pytest 9 下 -q 覆盖 -v 不打印 PASSED，output_match 退化陷阱）；输出断言仅用稳定子串 passed（逐用例名断言不做——用例名由实现轮命名，臆测必失配）。出处 spec/changes/add-alert-self-heal-marking/tasks.md Deliverables 与 1.4/2.2/3.2/4.2/5.3 | pass | 0/7 | - |
| cli-selfheal-config-quiet-window-fallback | 配置兜底·admin.self_heal_quiet_minutes 缺省 1440 且脏值回退（design D4、tasks 3.2、spec.md「安静窗口可配且脏值回退」场景）：get_admin_config 对缺失配置回 1440（盖过跨日同刻复发节律——指纹 822c197a 以 ≈24h 间隔复发，满窗才收口避免收后即重开）；显式 720 生效 720；-1（负数）/ 0（非正）/ "abc"（非 int）/ True（bool）一律回退 1440 不抛异常，巡检不因脏值中断（对齐既有脏值回退口径）。判定输入纯注入、模块不读文件。出处 core/config.py:1676（get_admin_config 段兜底）、design.md D4 | pass | 0/8 | - |
| cli-seed-selfheal-scratch-alerts | 供数（自复位幂等）·注册探针项目并播种四条已知告警，供后续 api/web 场景断言徽标与视图收纳：/tmp 探针工程（.fenix/STATE.md + config.yaml）经 Registry().add_project（fixture=False，与 add-alerts-archive-and-overview-cache arch-scratch 同通道）登记为 selfheal-scratch-verify，直写 .fenix/admin_alerts.json 四条——①未处理 daemon_errors escalation（待处理对照锚点，保证横幅渲染门 AlertBanner「无未处理不渲染」开启）；②收敛升级 escalation 已按 handled_by=auto-self-heal 自愈收口（created 序最新 handled 记录，徽标锚点）；③既有 auto-resolve 徽标回归锚点；④人工处理徽标回归锚点。轮询 /api/alerts?project= 至发现（≤30s，容忍项目注册传播）。合成项目名隔离，不触碰真实项目告警。出处 core/dashboard/registry.py（Registry.add_project）、core/dashboard/routes/alert_routes.py:83-137（/api/alerts 聚合与 ?project 作用域）、core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:105-107 | pass | 0/4 | - |
| api-config-selfheal-quiet-default-1440 | 正向路径·设置链路透出新配置键缺省（tasks 5.2）：GET /api/config（用户级）回显 admin.self_heal_quiet_minutes=1440——config_admin 受管 admin 键缺省填充与 ConfigLoader.get_admin_config 同源（1440），防设置页以旧缺省回填表单、用户直存即把错误缺省显式写回。出处 core/dashboard/routes/base.py:558（GET /api/config）、core/dashboard/data/config_admin.py:386-436（_ADMIN_DEFAULTS/_managed_admin_keys）、:953（result["admin"] 回显）、core/config.py:1676 | pass | 0/2 | - |
| api-config-selfheal-quiet-roundtrip | 交互流程·安静窗口写入往返（tasks 5.2 读写链路）：POST /api/config 提交 admin.self_heal_quiet_minutes=720 → 响应回显 720 → GET 读回 720（持久化生效）→ 写回 1440 恢复缺省并读回（自复位幂等：不把测试值遗留进运行环境、不污染后续场景）。出处 core/dashboard/routes/base.py:603（POST /api/config）、core/dashboard/routes/settings_routes.py:145-186（写回回读契约） | pass | 0/6 | - |
| api-alerts-selfheal-marking-exposure | 正向路径·告警数据层透出自愈标识与视图收纳（tasks 5.3、spec.md「安静超窗的 daemon_errors 信号自动自愈」THEN 后半）：GET /api/alerts?project=selfheal-scratch-verify（种子场景供数）——该形态返回 {project, alerts（项目全部记录，created 倒序）, summary}（无 resolved 键，alert_routes.py:100-105）；待处理计数 summary.unhandled_count=1（3 条 handled 自愈/既有/人工条目全部离开待处理口径，「待处理视图不再出现已自愈条目」的精确仲裁）；alerts[0] 为 created 最新的未处理对照锚点，alerts[1] 为自愈收口条目（seed created 定序：-30min/-48h/-70h/-72h），透出 handled=true、handled_by=auto-self-heal、resolve_note 以「已自愈：」前缀附安静证据。中文断言走 json_path（免 ensure_ascii 转义失配）。出处 core/dashboard/routes/alert_routes.py:100-105（?project 作用域）、core/dashboard/data/admin_alerts.py:58-67（get_alerts 全量 created 倒序） | pass | 0/8 | - |
| web-overview-selfheal-badge-resolved | 正向路径·概览页横幅「已自愈」徽标与已解决收纳（tasks 5.3、D6：待处理视图不再出现已自愈条目、条目自然落入已处理视图）：概览页告警横幅由未处理对照锚点撑起渲染门，已解决折叠区展开后自愈收口条目以「已自愈」徽标渲染（区别于既有 auto-resolve「自动解决」徽标文案），resolve_note 以「已自愈：」前缀附安静证据随「解决依据」可见；待处理对照锚点仍在待处理列表。数据源为真实 /api/alerts（禁止 mock 交付物端点；种子经 cli-seed-selfheal-scratch-alerts 落真实存储）。出处 core/dashboard/routes/base.py:970-971（根路径服务 dist/index.html）、core/dashboard/static/src/app.tsx:123（#/overview 路由）、core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:259-283（已解决折叠区）、core/dashboard/static/src/components/alert-shared.tsx:52-53（handled_by 徽标映射改造点） | pass | 0/7 | - |
| web-activities-selfheal-badge-mapping-regression | 回归点·运维页人工告警视图三种徽标并存互不混淆（tasks 5.3 徽标映射改造的回归面）：切换「人工告警」视图后，已解决折叠区默认展开，同屏可见——已自愈（auto-self-heal 新映射）、🤖 自动解决（auto-resolve 既有映射不回归）、👤 人工处理（人工记录映射不回归）；自愈收口条目锚点在已解决区渲染。出处 core/dashboard/static/src/app.tsx:134（#/activities 路由）、core/dashboard/static/src/pages/activities/index.tsx:282-297（已解决 Collapse defaultActiveKey 默认展开）、:481（view-mode-switch）、alert-shared.tsx:52-53 | pass | 0/7 | - |
| api-config-selfheal-quiet-invalid-rejected | 异常路径·非法安静窗口被服务端拒绝且不落盘（tasks 5.2「非法值拒绝并报错」）：POST admin.self_heal_quiet_minutes=-1（负数）/ "abc"（非数字）/ true（bool）均 400 拒绝（对齐既有受管键写路径前置校验 fail 形态）；随后 GET 读回仍 1440——脏值未落盘、巡检不因脏值中断。出处 core/dashboard/data/config_admin.py:1372-1470（write_config 前置校验 fail → 400）、core/dashboard/routes/settings_routes.py:160-163 | pass | 0/5 | - |
| web-settings-selfheal-quiet-field-default | 正向路径·设置页系统页签新增安静窗口字段并按缺省回填（tasks 5.2）：「系统」页签系统分组出现「告警自愈安静窗口」数字输入（SystemPanel ADMIN_ANNOTATIONS 声明式字段表新增项，沿用 system-field-*/system-control-* testid 约定），表单按当前配置 1440 回填（此链配置已被 api 场景恢复缺省）。出处 core/dashboard/static/src/pages/settings/app.tsx 无、settings/index.tsx:473（SystemPanel 挂载）、pageLabels.ts:24（系统页签）、core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:21-118（ADMIN_ANNOTATIONS）、:133/:154/:160（system-field-*/system-control-* testid 约定）、app.tsx:133（#/settings 路由） | pass | 0/5 | - |
| web-settings-selfheal-quiet-save-roundtrip | 交互流程·设置页安静窗口修改保存持久化（tasks 5.2「走既有面板脏检查与提交链路」）：系统页签安静窗口输入 720 → 保存 → 离开再重进 → 表单回显 720（用户级配置持久化生效；断言只在步骤全部结束后执行，故持久化断言取重进后的最终态）。出处 SystemPanel.tsx:521（system-save-btn）、settings/index.tsx:195/:216（系统页签保存链路与「保存成功」toast）、settings_routes.py:145-186（POST /api/config 用户级写盘） | pass | 0/5 | - |
| web-settings-selfheal-quiet-restore-default | 回归点·安静窗口恢复缺省（自复位收尾）：把上一场景改写的 720 改回 1440 并保存重进确认——运行环境不遗留测试值，且「改回缺省值」的写盘路径与 720 等价可用。出处 SystemPanel.tsx:521、settings/index.tsx:216、settings_routes.py:145-186 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

