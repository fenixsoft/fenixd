## Deliverables

```yaml
- path: core/agent_runner/harness/__init__.py
  kind: new
- path: core/agent_runner/harness/protocol.py
  kind: new
- path: core/agent_runner/harness/claude_adapter.py
  kind: new
- path: core/agent_runner/harness/one_shot.py
  kind: new
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: core/dashboard/routes/architecture_routes.py
  kind: modify
- path: core/dashboard/routes/project_routes.py
  kind: modify
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: core/config.py
  kind: modify
- path: core/proc_utils.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: bin/fenix_dashboard.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: spec/knowledge/adr/ADR-271-pluggable-agent-harness.md
  kind: new
- path: spec/knowledge/adr/index.md
  kind: modify
- path: tests/test_harness_adapter.py
  kind: new
- path: tests/test_harness_config.py
  kind: new
- path: tests/test_harness_claude_snapshot.py
  kind: new
- path: .fenix/config.yaml
  kind: reference
```

## 1. 协议层与数据类

- [x] 1.1 新建 core/agent_runner/harness/ 包：protocol.py 定义 HarnessAdapter 协议（name/build_spawn_spec/normalize_event/classify_stderr/extract_result/process_patterns/capabilities）与 SpawnRequest/SpawnSpec/HarnessCapabilities 数据类，HarnessCapabilities 可 json 序列化，__init__.py 导出公共名
- [x] 1.2 单测（tests/test_harness_adapter.py）：claude_adapter 实例满足协议成员完整性、HarnessCapabilities 可 json.dumps 往返

## 2. claude_adapter 平移

- [x] 2.1 平移命令构造进 claude_adapter.build_spawn_spec：`claude -p --output-format stream-json --verbose --add-dir … --permission-mode bypassPermissions [--settings][--model][--resume]` 全参数、prompt 经 stdin 载荷、max_turns daemon 侧强制语义保持
- [x] 2.2 平移隔离 settings 构造与落盘（_build_isolated_settings/_ensure_agent_config_dir、3 个 PreToolUse hooks 注入、skills/plugins symlink、enabledPlugins、子代理模型映射、ISOLATED_SETTINGS_SCHEMA_VERSION）
- [x] 2.3 平移 env 路由与清理（ANTHROPIC_* 注入、ANTHROPIC_AUTH_TOKEN 清除、CLAUDE_CONFIG_DIR 隔离、AGENT_RUN_BANNED_ENV_KEYS 应用点、FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE 注入）
- [x] 2.4 快照测试（tests/test_harness_claude_snapshot.py）：迁移动手前先以现状 _run_claude 捕获代表性 SpawnRequest 集合（spec 车道/维护车道/resume/provider 链各至少一例）的 argv/env/stdin 金样本 fixture 并入库；迁移后以同一 SpawnRequest 集合驱动 claude_adapter.build_spawn_spec 与金样本逐字节相等对照
- [x] 2.5 平移 stderr 分类与结果提取进 claude_adapter：classify_stderr 承接现状 stderr 降噪/归因（unrecognized_model 分类保持经 ProviderCircuit.classify_unrecognized_model_error 委托的接入形态，runner.py:725）；extract_result 承接会话 id/usage（_extract_usage_info）/终态 result 提取的现状行为（由 3.2 既有回归覆盖）

## 3. 主通道两段化

- [x] 3.1 _run_claude 改名 _run_agent 并拆为「build_spawn_spec → 通用 Popen + 归一化事件写盘」两段，claude normalize_event 为恒等映射；attempt 环/max_turns 守护/五路监督/终态收口语义不动；解除「有意单体」注记（runner.py:5659-5664）并以指向 harness 包的注释替代，替代注释 MUST 保留行序契约警示（run_metrics 行与终态行次序由权威测试 test_run_claude_poll_loop_crash_writes_error_terminal 锁定，改动前先跑该测试；快照测试只护 argv/env/stdin、不护事件行序）
- [x] 3.2 回归验证：agent_runner 既有测试全绿（终态事件类型/会话提取/usage 解析/在飞判定不变）

## 4. 一次性 spawn 收编与叙事通道

- [x] 4.1 新建 harness/one_shot.py 的 run_one_shot(adapter, …)；收编五个一次性 spawn 点：监督 judge（liveness.py，`--output-format json` argv 传 prompt）、知识蒸馏（knowledge.py）、知识回填（knowledge_backfill.py）、架构图 autodraft（architecture_routes.py）、项目简介（project_routes.py），各自参数形态经 claude_adapter 保持
- [x] 4.2 adjudication_narrative 的 default_channel 改为经 set_channel 注入的 adapter 化实现，模型显式传递不依赖 CLI 默认档
- [x] 4.3 测试替身验证：judge/蒸馏两形态捕获 argv 与收编前一致；叙事通道触发行为一致

## 5. 进程识别泛化

- [x] 5.1 process_patterns() 纳入协议；proc_utils.py:47、event_bus.py:810、admin_monitor.py:868、bin/fenix_dashboard.py:151-154 四处消费点改为从 adapter 获取，claude 值与现状全等
- [x] 5.2 测试：构造 `claude -p` 测试进程验证识别命中/豁免行为不变（killpg 自保护守卫不受影响）

## 6. 配置与设置页

- [x] 6.1 core/config.py 支持 agent.harness（合法值 claude|dsh、缺省 claude、非法值回退+告警日志）；.fenix/config.template.yaml 增加注释样例，且注释须显式区分新顶层段 agent（harness 进程边界选择）与既有 agents 段（按 agent 类型的 models/timeout_overrides/退避段），避免两段混用
- [x] 6.2 harness 工厂 _resolve_adapter：claude→claude_adapter；dsh→抛明确错误「dsh adapter 未部署（add-dsh-adapter-integration 交付）」；dispatch 前置健康检查接入该工厂
- [x] 6.3 settings_routes 提供 agent.harness 读写（同校验、dsh 值保存被拦）；SystemPanel.tsx 增加系统级 harness 选择控件（claude/dsh，dsh 附未部署提示文案）
- [x] 6.4 前端构建产物重建并冒烟验证设置页控件可见可用
- [x] 6.5 测试（tests/test_harness_config.py）：缺省/非法回退/dsh fail-fast 三场景 + 热重载后新值对下次 dispatch 生效、在飞 run 不受影响

## 7. ADR-271

- [x] 7.1 撰写 spec/knowledge/adr/ADR-271-pluggable-agent-harness.md：取代 ADR-055，记录自由会话/CLAUDE_PID watchdog 豁免、run jsonl claude stream-json canon、worktree 目录约定冻结三项决策
- [x] 7.2 spec/knowledge/adr/index.md 登记 ADR-271；ADR-055 引用处加「被 ADR-271 取代」注记（不重写原文）

## 8. 收尾验证

- [ ] 8.1 全量测试绿 + 编译自洽（python -m compileall core）；快照测试结果作为行为零变化的对照证据写入合并说明
- [ ] 8.2 全仓 grep 核查：五个一次性 spawn 点与叙事通道不再直接构造 claude 命令，车道与一次性 spawn 的命令构造唯一入口在 harness/claude_adapter.py；dashboard 自由会话（session_manager）与 CLAUDE_PID watchdog 为 ADR-271 豁免项、仍直连 claude，不计入本核查范围
