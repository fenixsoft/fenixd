# 验证报告：add-harness-adapter-layer

> ⚠️ 本报告由框架于 2026-10-13T06:11:06Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-13T06:11:05.832775+00:00+run-result@mtime1791871865870161241

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.08M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| harness-protocol-integrity | 协议完整性：core/agent_runner/harness 包导出 HarnessAdapter/SpawnRequest/SpawnSpec/HarnessCapabilities 公共名；claude adapter 实例七个协议成员（name/build_spawn_spec/normalize_event/classify_stderr/extract_result/process_patterns/capabilities）全部在场可调用；HarnessCapabilities 可 json.dumps 往返；process_patterns 返回字符串列表且覆盖 claude；normalize_event 对 claude stream-json 原生事件为恒等映射（输出与输入等价）。出处：spec/changes/add-harness-adapter-layer/specs/agent-harness-adapter/spec.md（HarnessAdapter 协议/事件归一化为恒等映射）、tasks.md 1.1/1.2 | pass | 0/11 | - |
| harness-resolve-dsh-failfast | dsh 值 fail-fast：harness 工厂 _resolve_adapter 对 claude 返回 claude adapter；对 dsh 抛出明确错误（含「未部署」与交付 SPEC 名 add-dsh-adapter-integration），绝不静默回退 claude。出处：specs/harness-config/spec.md（dsh 值 fail-fast）、tasks.md 6.2、design.md 决策 4 | pass | 0/7 | - |
| harness-config-resolution-matrix | agent.harness 配置解析矩阵：config.yaml 不含该键时解析为缺省 claude；非法值 codex 回退 claude 且日志出现含「不支持」字样的告警、不中断；dsh 值被校验接受（schema 前瞻，不回退不崩溃，部署拦截交给工厂健康检查）。出处：specs/harness-config/spec.md（缺省行为/非法值回退并告警）、tasks.md 6.1，ConfigLoader.load/get 形态见 core/config.py:201/3362 | pass | 0/7 | - |
| harness-claude-snapshot-tests-green | claude 平移字节级等价快照测试全绿：tests/test_harness_claude_snapshot.py 以代表性 SpawnRequest 集合（spec 车道/维护车道/resume/provider 链各至少一例）断言 build_spawn_spec 平移前后 argv/env/stdin 逐字节相等。出处：specs/agent-harness-adapter/spec.md（快照测试逐字节对账）、tasks.md 2.4 | pass | 0/2 | - |
| harness-adapter-config-suites-green | adapter 与 config 单测套件全绿：tests/test_harness_adapter.py（协议成员完整性/HarnessCapabilities json 往返）与 tests/test_harness_config.py（缺省/非法回退/dsh fail-fast/热重载后新值对下次 dispatch 生效、在飞 run 不受影响）全部通过。出处：tasks.md 1.2/6.5 | pass | 0/2 | - |
| harness-one-shot-consolidation-grep | 一次性 spawn 收编核查：监督 judge（liveness.py:1053）、知识蒸馏（knowledge.py Popen）、知识回填（knowledge_backfill.py:883）、架构图 autodraft（architecture_routes.py:659）、项目简介（project_routes.py:597）五个 spawn 点与叙事通道（adjudication_narrative.py:342）源码不再直接构造 claude 命令（AST 层核查 argv 列表与 --output-format 字面量，排除 docstring）；唯一命令构造入口 harness/claude_adapter.py 在场且持有 canon 形态（-p --output-format stream-json）；run_one_shot 收编入口可导入；dashboard 自由会话豁免保持 claude 专用直构（core/dashboard/session_manager.py:101-104 的 --input-format stream-json 形态不动）。出处：specs/agent-harness-adapter/spec.md（一次性 spawn 收编/dashboard 自由会话豁免）、tasks.md 4.1/8.2 | pass | 0/11 | - |
| harness-process-identification-parity | 进程识别泛化等价：adapter.process_patterns() 供给非空模式列表且覆盖 claude（与 proc_utils.py:47 现状 basename 集合全等语义）；以 argv0 伪装成 claude 的测试进程被识别函数命中（proc_utils.is_claude_process 口径），普通 sleep 进程不命中（豁免行为不变）。出处：specs/agent-harness-adapter/spec.md（进程识别泛化/识别结果与现状一致）、tasks.md 5.1/5.2 | pass | 0/7 | - |
| harness-main-channel-two-stage | 主通道两段化不改行为：_run_claude 已改名 _run_agent（旧名消失）；runner 以 import 形式接入 harness 包（build_spawn_spec 段）；「有意保持单体内联」注记解除；RUN_TERMINAL_EVENT_TYPES 六成员（result/interrupted/error/cancelled/frozen-terminated/gate-blocked）判定不变。出处：specs/agent-harness-adapter/spec.md（主通道两段化不改行为/终态事件语义不变）、tasks.md 3.1，注记现状 runner.py:5659、终态常量 liveness.py:133 | pass | 0/7 | - |
| harness-adr-and-template-landed | ADR-271 与配置模板落盘：spec/knowledge/adr/ADR-271-pluggable-agent-harness.md 在场且记录取代 ADR-055、自由会话/CLAUDE_PID watchdog 豁免、run jsonl claude stream-json canon 三项决策；adr/index.md 登记 ADR-271 且 ADR-055 条目带取代注记（不重写原文）；.fenix/config.template.yaml 增补 agent.harness 注释样例（与新配置带界面规则同步存在）。出处：specs/agent-harness-adapter/spec.md（dashboard 自由会话豁免）、specs/harness-config/spec.md（新配置带界面）、tasks.md 7.1/7.2/6.1 | pass | 0/9 | - |
| api-harness-user-scope-default-echo | 空状态：用户级配置读取（无 project 参数=用户作用域）在未配置 agent.harness 时回显缺省 claude。出处：core/dashboard/routes/base.py:596（GET /api/config 路由）、core/dashboard/routes/settings_routes.py:156（_api_config_get 用户级分支） | pass | 0/2 | - |
| api-harness-project-scope-default-echo | 空状态：项目级作用域（夹具项目 scheduling-showcase，verify.yaml prepare 层每轮幂等供给）读取有效配置，未配置 agent.harness 时回显缺省 claude。出处：core/dashboard/routes/settings_routes.py:175（read_effective_config）、.fenix/verify.yaml prepare 夹具供给段 | pass | 0/2 | - |
| web-harness-control-visible-with-options | 设置页系统页签提供 agent.harness 查看能力：系统级面板存在 harness 选择控件（system-field-harness/system-control-harness），缺省显示 claude，下拉含 dsh 选项且附「未部署」提示文案（dsh adapter 未部署阶段）。出处：core/dashboard/static/src/app.tsx:133（/settings SPA 路由）；控件 testid 约定 core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:151-221（system-field-*/system-control-* 按配置键名生成）、:546（system-save-btn） | pass | 0/6 | - |
| api-harness-dsh-save-rejected | dsh 值保存被拦：POST /api/config 提交 agent.harness=dsh（dsh adapter 未部署阶段）被校验拦截返回 400，配置值不变（读回仍 claude），无静默落盘。出处：specs/harness-config/spec.md（Dashboard 设置界面同步——保存请求被校验拦截并返回明确错误；配置值不变）、tasks.md 6.3、core/dashboard/routes/settings_routes.py:180（_api_config_post 校验失败 400 分支） | pass | 0/4 | - |
| api-harness-illegal-value-never-effective | 异常输入：未支持的 harness 值 codex 经保存通道后永不生效——读回有效配置仍为 claude（保存侧拒绝或归一均视为合规，裁决点在读回值）。出处：specs/harness-config/spec.md（非法值回退）、core/dashboard/data/config_admin.py:1446（受管字段局部校验、非法拒绝不落盘口径） | pass | 0/2 | - |
| api-harness-claude-save-readback | 正向路径：显式保存 agent.harness=claude 走 settings_routes 同一校验通道，返回 saved=true 与最新配置读回（agent.harness=claude），保存-读回闭环。出处：core/dashboard/routes/settings_routes.py:180-214（写后读回以确认）、tasks.md 6.3 | pass | 0/5 | - |
| web-harness-dsh-save-not-persisted | 交互异常路径：在设置页系统页签把 harness 从 claude 改为 dsh 并保存（dsh adapter 未部署阶段）——无论前端禁用选项、前端校验拦截还是后端 400 拒绝，dsh 都不得生效；刷新后控件仍显示 claude。写路径走项目级作用域（夹具项目 scheduling-showcase，每轮复位），不写用户级真实配置。出处：core/dashboard/static/src/app.tsx:133（/settings SPA 路由）；控件 testid 约定 core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:151-221（system-field-*/system-control-* 按配置键名生成）、:546（system-save-btn） | pass | 0/3 | - |
| web-harness-claude-save-persists | 交互正向路径：设置页系统页签显式选择 claude 并保存 → 表单载荷含 agent.harness 走保存通道；刷新并重进系统页签后仍显示 claude。写路径走项目级作用域（夹具项目 scheduling-showcase，每轮复位）。出处：core/dashboard/static/src/app.tsx:133（/settings SPA 路由）；控件 testid 约定 core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:151-221（system-field-*/system-control-* 按配置键名生成）、:546（system-save-btn） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

