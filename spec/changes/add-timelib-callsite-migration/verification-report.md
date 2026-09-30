# 验证报告：add-timelib-callsite-migration

> ⚠️ 本报告由框架于 2026-09-30T06:34:20Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-30T06:34:20.856657+00:00+run-result@mtime1790750060891548914

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.06M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| timelib-guard-whitelist-cleared-and-ratchet-armed | 守卫白名单清零：tests/test_timelib_guard.py 全过（含僵尸检测与新违例拦截机制用例），且 TIME_WHITELIST 运行时长度为 0（SPEC specs「守卫白名单清零」两 Scenario：守卫零白名单通过 + 迁移完成后新违例仍被拦截） | pass | 0/6 | - |
| bin-cli-time-primitives-consolidated | bin/ 三 CLI 脚本时间原语收拢：_local_ts 私有助手退役、无 fromisoformat 裸解析、无零参 datetime.now() 与裸 fromtimestamp（守卫不扫 bin/，此为源码面机械验收；proposal「CLI 展示脚本统一 fmt_display」）（裁决修复：g-localts 验收面锚定 SPEC 退役两文件、g-iso/g-now 加 --include="*.py" 排二进制缓存瞬态；断言 expected 未动） | pass | 0/7 | - |
| cli-fmt-display-three-forms-equivalence | fmt_display 三形态输入（Z 后缀/+00:00 后缀/无后缀）在 TZ=Asia/Shanghai 下输出锁定：前两形态折算本地 +8，无后缀按本地解读原样（SPEC specs「CLI 展示展示输出不变」等价口径，出处 core/timelib.py:96 fmt_display 语义） | pass | 0/2 | - |
| cli-fenix-process-report-smoke | bin/fenix_process.py 真实渲染进程报告：从验证实例 STATE store 自选一个 spec 渲染完整报告（不绑定具体 spec 名，对任意非空 store 稳健；空 store 显式失败），端到端走迁移后展示链路（出处 bin/fenix_process.py:262 render_report、:24 PROJECT_ROOT 解析；snippet 机制已在当前树实测） | pass | 0/3 | - |
| cli-display-contract-suite-green | CLI 展示契约测试套件 tests/test_cli_time_display.py 全过（实现方按 D5 同批改写该文件锁定 fmt_display 迁移后契约，场景只断全绿；proposal「展示输出格式保持与迁移前一致」） | pass | 0/3 | - |
| self-review-schedule-semantics-aware-utc | self_review 调度语义边界：_parse_run_at('23:00') 在 TZ=Asia/Shanghai 下产出与当日 15:00Z 同一时刻的 aware datetime（探针显式 astimezone(utc) 检验换算规则，并正面断言 utcoffset=+08:00 证明非 naive）、非法配置回退缺省 02:00（→前日 18:00Z 等价时刻）、配置字面值 SELF_REVIEW_DEFAULT_RUN_AT='02:00' 不变（SPEC specs「调度时刻语义保持本地墙钟」+ Req「域迁移不越界」，出处 core/self_review.py:213 _parse_run_at、core/config.py:61）（裁决修复：场景文件缺陷——原断言锁死 UTC 字符串表示形态且 negate 子串断言无法区分 naive/aware，实现按 design D2 用 .astimezone() 本地化（+08:00 aware 与 15:00Z 同一时刻）正确；探针改为显式转 UTC 输出并正面断言 utcoffset，检验强度提升非弱化：断言 expected 未放松） | pass | 0/7 | - |
| self-review-window-suite-regression | self_review 域全家桶测试回归全绿：窗口快照/run 语义/调度触发/中途/终态交叉/归档统计/结果分类七件套——窗口判定等价基准（迁移前固化的 characterization 快照测试不得因 aware 迁移而改写期望集合）（SPEC specs「窗口判定等价」；tasks 1.3，出处 tests/test_self_review_window_snapshot.py 等） | pass | 0/3 | - |
| domain-agent-runner-fenixd-regression | 批② agent_runner 域与入口迁移回归：agent_runner 主套件/门禁/模块契约/characterization/liveness 判别五件全绿——fromtimestamp→from_epoch、fromisoformat→parse_ts 后行为锁定（tasks 2.1-2.3「行为以既有测试锁定」） | pass | 0/1 | - |
| domain-pm-admin-regression | 批③ pm_engine 与 admin/store 域迁移回归：state_machine/admin/admin_store 归档+损坏/admin_monitor 告警生命周期/pm_engine dispatch/退避判定的既有测试全绿——退避、升级、告警判定边界不变（tasks 3.1-3.2「告警时间戳与 TUI 展示格式不变」） | pass | 0/1 | - |
| domain-dashboard-scatter-regression | 批④ dashboard data 与散点域迁移回归：dashboard data 主套件/characterization/模块契约/freeze(frozen_until)/spec_archive/code_review/regression 契约既有测试全绿——dashboard 只读契约（容错、不抛）保持（tasks 4.1-4.2） | pass | 0/1 | - |
| deploy-copy-refresh-registered | .fenix/bin 部署副本刷新人工步骤已登记：.fenix/todo.md 或 docs/ 中可 grep 到 .fenix/bin 部署副本刷新说明（未跟踪文件不随 merge-back 落地）（SPEC specs「部署副本刷新已登记」；tasks 5.3，design D3） | pass | 0/3 | - |
| dashboard-read-contract-intact | dashboard 只读 API 契约在时间戳 aware 化后保持：/api/specs?project=fenixd 200 + {project,specs} 形状（v1 兼容契约，未知项目仍 200 空表）、/api/overview 与 /api/alerts 200 JSON object——aware 解析不得使只读端点 5xx（tasks 4.1「dashboard 只读契约保持」，出处 core/dashboard/routes/spec_routes.py:74、core/dashboard/routes/base.py:524-531） | pass | 0/6 | - |
| frontend-time-render-overview-no-invalid-date | 概览页时间渲染无 Invalid Date：v1 SPA（8787 根）加载后页面不出现 dayjs 解析失败的 Invalid Date 文本——aware 串（+00:00/Z 后缀）可被前端正常解析（tasks 4.1「抽查 dashboard API 时间字段在前端 dayjs 渲染无 Invalid Date」；URL 出处：8787 根=v1 SPA 静态托管 core/dashboard/routes/base.py:524 路由族，既有验证场景惯例） | pass | 0/4 | - |
| frontend-time-render-project-no-invalid-date | 项目详情页时间渲染无 Invalid Date：#project/fenixd 详情页 spec 列表 updated/frozen_until 等时间字段渲染正常、无 Invalid Date、无控制台错误（tasks 4.1；URL 出处：hash 路由 #project/fenixd，既有验证场景惯例 + core/dashboard/routes/base.py:524 路由族） | pass | 0/3 | - |
