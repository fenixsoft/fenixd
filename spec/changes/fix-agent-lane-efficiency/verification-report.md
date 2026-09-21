# 验证报告：fix-agent-lane-efficiency

> ⚠️ 本报告由框架于 2026-09-20T17:45:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T17:45:51.394030+00:00

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.96M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| subagent-model-injection-tests-pass | 子代理模型注入全量测试通过（直连 provider env 映射/override 优先级/默认网关零写入/幂等重建/死键不回退），覆盖 subagent-model-availability（tests/test_subagent_model_injection.py，def test_* 真名） | pass | 0/7 | - |
| prompt-lane-efficiency-sections-pass | 长车道动态契约段测试全量通过（三车道工具调用效率段/评审取证深度段/实现车道长任务段/非目标车道零注入/顺序不变式），覆盖 agent-tool-call-efficiency + long-task-foreground-wait + agent-prompt-files（tests/test_prompt_lane_efficiency_sections.py，@pytest.mark.parametrize 用例名带 [agent] 后缀） | pass | 0/9 | - |
| run-token-economy-metrics-pass | 上下文经济性指标与 run_metrics 转录字段测试全量通过（指标必填字段/per-turn 计算/零轮处理/超阈值告警与不阻断/最小样本门槛/读侧落盘），覆盖 agent-run-token-economy + agent-run-artifacts（tests/test_run_token_economy.py） | pass | 0/6 | - |
| impl-resultfile-contract-anchored | 在飞契约同步后 impl 结果文件硬门测试不断红（能力事实保留 + 旧「无后台节拍」锚点废弃 + 其余回归不破），覆盖 agent-prompt-files 措辞修正（tests/test_impl_resultfile_contract.py，@pytest.mark.parametrize 用例名带 [agent] 后缀） | pass | 0/4 | - |
| probe-cache-script-error-exit | 缓存探针参数错误路径确定性契约（不存在的 provider → 合法 JSON 判据含 cache_supported:null/error，exit 1），覆盖 agent-run-token-economy 探针脚本 main（bin/probe_prompt_cache.py:main 退出码 1 + _load_provider None） | pass | 0/4 | - |
| probe-cache-judgement-output | 缓存探针正常路径确定性 JSON 判据（provider/cache_supported/evidence 字段存在；本地不可达 baseurl 时 rounds 记录 URLError、cache_supported=false、exit 0——不依赖外网，确定性复现 D3 定案行为），覆盖 agent-run-token-economy「探针输出确定性判据」Scenario（bin/probe_prompt_cache.py probe() 逻辑） | pass | 0/5 | - |
| settings-subagent-model-input-visible | Dashboard 设置页「模型分配」面板包含「子代理模型覆盖」输入控件并可输入值（配置键与 UI 同步铁律——agents.subagent_model_override UI 承载，core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx:204-207 Form.Item + input；设置页路径 /settings 见 app.tsx:111 菜单 + config/routes.ts hash 路由；菜单项「模型分配」label 来自 BASE_MENU_ITEMS:agents，settings/index.tsx:47）。不执行保存（避免写用户级真实配置；配置键读侧由 api 场景与 CLI 测试覆盖）。 | pass | 0/6 | - |
| api-config-subagent-model-keys | GET /api/config 用户级回显含 subagent_model_override（string）与 context_cost_per_turn_threshold（integer）两键（config_admin 受管键白名单读侧：config_admin.py:108/437 subagent_model_override 回显、:95/512 context_cost_per_turn_threshold 回显；settings_routes._api_config_get → read_config(scope='user')，settings_routes.py:32）；验证端点为本 SPEC 修改物，打真实实例（api 场景，不 mock）。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

