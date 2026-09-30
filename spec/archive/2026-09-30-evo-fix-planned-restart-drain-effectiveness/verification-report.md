# 验证报告：evo-fix-planned-restart-drain-effectiveness

> ⚠️ 本报告由框架于 2026-09-24T10:33:17Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T10:33:17.444651+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.10M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| planned-drain-e2e-suite-green | SPEC 交付的端到端回归套件存在且全绿：tests/test_planned_restart_drain_e2e.py 以替身进程驱动真实 shutdown 路径（tasks 3.1）。pytest -v 运行退出码 0 且输出含 passed（只 -v 不带 -q，保证 PASSED 行打印）。出处：spec specs/planned-restart-drain-effectiveness/spec.md「Requirement: 端到端回归钉住」、tasks.md 3.1 | pass | 0/3 | - |
| drain-zero-fast-path-semantics-narrowed | drain=0 fast path 语义收窄后三个排水语义用例通过：test_drain_zero_fast_path（修订为 fast path 仅非规划性关停）、test_planned_restart_drains、test_non_planned_restart_fast_path 用 -k 过滤运行并逐一断言 PASSED（无 parametrize 后缀，用例名稳定）。出处：specs spec.md「Scenario: drain=0 fast path 语义收窄」、tasks.md 3.2、tests/test_interrupt_recovery_preserve.py:551/562/573 | pass | 0/4 | - |
| interrupt-recovery-drain-suite-regression | 既有中断恢复/排水测试文件全量回归不破：tests/test_interrupt_recovery_preserve.py 整文件 pytest 退出码 0（其余排水用例回归不变，含 sigkill_wait parametrize 用例由 exit_code 仲裁）。出处：tasks.md 3.2「其余排水用例回归不变」 | pass | 0/2 | - |
| pipeline-governance-planned-exempt-units | 吞吐治理测试文件全绿：tests/test_pipeline_throughput_governance.py 含新增规划性豁免分支单测（planned 在场不受 shutdown=0 夹紧、窗口受 supervisor SIGKILL 上界）且既有非规划性夹紧用例 test_drain_window_clamped_by_shutdown_drain 保持通过。出处：tasks.md 3.2、tests/test_pipeline_throughput_governance.py:233 | pass | 0/3 | - |
| config-planned-exemption-behavior-probe | 配置层夹紧豁免行为黑盒探针（tasks 1.1 合同：core/config.py 的 get_run_drain_max_seconds 支持规划性豁免）：断言非规划性 min 夹紧保持（600/300→300）、drain=0 非规划性快速停机语义保留（60/0→0）、shutdown>0 部署行为不变（600→600）、planned 形参在场时 shutdown=0 不夹紧（0<窗口≤60 原值，豁免不解除 supervisor 上界）。出处：specs spec.md「Requirement: 规划性重启不受快速停机夹紧」、tasks.md 1.1、design.md D1 | pass | 0/2 | - |
| lane-registry-and-ocr-drain-probe | 车道级排水集合探针（tasks 2.1/2.2 合同）：core/agent_runner/runner.py 暴露 register/unregister 登记/注销 API（类属性或模块级任一形态）；core/agent_runner/maintenance_runs.py 的 run_impl_ocr 将 ocr 子进程登记进排水集合（现状 0 处 register，断言有鉴别力）；超窗有序终止具备 SIGTERM/terminate 与 SIGKILL/kill 语义（design D3，现状两词均 0 处）。出处：specs spec.md「Requirement: 车道级进程纳入排水集合」、tasks.md 2.1/2.2、design.md D2/D3 | pass | 0/2 | - |
| planned-restart-drain-observability-probe | 可观测性探针（tasks 1.2 / spec「夹紧禁用可观测」）：fenixd.py 存在排水相关 WARNING 日志调用（规划性重启但排水被配置禁用时告警；现状 0 行排水 warning，断言有鉴别力），且 broadcast_restart_checkpoint 排水路径附近记录排水集合清单（在飞 run/排水集合/在飞字样）。出处：specs spec.md「Scenario: 夹紧禁用可观测」、tasks.md 1.2、fenixd.py:3671-3686 | pass | 0/2 | - |
| ops-doc-planned-restart-semantics | 运维文档补齐规划性重启排水新语义与过渡指引（tasks 3.3）：docs/help/14-pipeline-throughput-ops.md 含「规划性」「豁免」「过渡」关键词（三词现状文档均不存在，断言可区分新旧语义；联动说明与 shutdown_drain_seconds 调正值运维指引落文）。出处：tasks.md 3.3、design.md Non-Goals 3、docs/help/14-pipeline-throughput-ops.md:44（现状旧语义待修订） | pass | 0/5 | - |
| help-api-doc-name-guard | 帮助文档端点异常路径守卫回归：不存在文档名返回 404；路径穿越形态（..%2f 前缀）不匹配文件名白名单返回 400 且错误体为 invalid help doc name（防穿越既有行为不被本 SPEC 破坏）。出处：core/dashboard/routes/help_routes.py:71-84 | pass | 0/3 | - |
| planned-drain-e2e-covers-three-lanes | e2e 回归文件内容覆盖三类在飞工作与关键机制：驱动 restart_request 规划性重启、构造 evo 分析 run / implementer run / OCR 车道三类替身、断言 checkpoint 旗标广播与超窗有序终止（tasks 3.1，防空转测试文件）。file_content 子串断言全部为 SPEC 点名机制词。出处：tasks.md 3.1、design.md D4 | pass | 0/5 | - |
| help-api-serves-throughput-ops-doc | 帮助 API 供出修订后的 14 号运维文档：GET /api/help/docs 清单含 14-pipeline-throughput-ops.md，GET /api/help/doc?name=14-pipeline-throughput-ops.md 返回 200 且 content 含新语义「规划性」（dashboard _json ensure_ascii=False，中文 body_contains 免转义失配）。出处：core/dashboard/routes/help_routes.py:31-65/:87-95、core/dashboard/routes/base.py:678 | pass | 0/5 | - |
| help-page-renders-throughput-ops-doc | 帮助页渲染修订后的 14 号文档：navigate v1 帮助页（hash 路由），点击目录中「14 管道吞吐运维」菜单项，正文渲染区含新语义「规划性」文本。出处：core/dashboard/static/src/app.tsx:124 /help 路由、core/dashboard/static/src/pages/help/index.tsx:372-378（桌面布局 Menu 目录+Markdown 正文）、core/dashboard/routes/base.py:581 GET / | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

