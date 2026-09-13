# 验证报告：add-stale-code-selfheal

> ⚠️ 本报告由框架于 2026-09-12T15:12:42Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 11.98M |
| 本链增量 Token（输出） | 0.09M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-config-defaults-user | GET /api/config（用户级作用域）返回 stale_code_selfheal 缺省值 enabled=true / idle_confirm_seconds=120（配置缺失时缺省值生效；出处 core/dashboard/data.py:4069 缺省回显、core/config.py:922 get_stale_code_selfheal_config） | pass | 0/4 | - |
| api-config-defaults-project-fenixd | GET /api/config?project=fenixd（项目级生效配置）返回 stale_code_selfheal 缺省 enabled=true / idle_confirm_seconds=120（主树 .fenix/config.yaml 无该节→缺省透传；出处 core/dashboard/data.py:4337 read_effective_config 经 ConfigLoader 回显） | pass | 0/3 | - |
| api-config-invalid-rejected | POST /api/config 提交非法 stale_code_selfheal 值（enabled 非布尔 / idle_confirm_seconds 负数 / 非数字）被后端 400 拒绝且不写盘（服务端权威校验；出处 core/dashboard/data.py:4632-4645 write_config 前置校验），随后 GET 确认配置未被污染仍为缺省 120 | pass | 0/6 | - |
| api-config-write-roundtrip-default | POST /api/config（用户级）写入缺省等值 stale_code_selfheal {enabled:true, idle_confirm_seconds:120} 返回 200 并回显，GET 读回一致（写路径合法值往返；出处 core/dashboard/data.py:4472-4481 两键合并、core/dashboard/server.py:1892 _api_config_post） | pass | 0/6 | - |
| web-panel-defaults-display | Dashboard 设置页「自愈」页签挂载 StaleCodeSelfhealPanel 并展示缺省值：开关开启、连续空闲秒数 120（navigate 路由出处 core/dashboard/static/src/app.tsx:111 /settings；菜单项 index.tsx:33 selfheal 自愈；面板 testid 出处 components/StaleCodeSelfhealPanel.tsx:54,67,98） | pass | 0/6 | - |
| cli-config-behavior | ConfigLoader.get_stale_code_selfheal_config 纯函数行为：节缺失→缺省 true/120；idle_confirm_seconds=-5（非正整数）→回退 120；enabled='yes'（非布尔）→回退 true，均不抛异常（非法值回退不中断；出处 core/config.py:922-963） | pass | 0/7 | - |
| cli-unit-tests-stale-selfheal | tests/test_stale_code_selfheal.py 回归组全绿：陈旧持续状态/告警去重、空闲判定与自愈触发、配置缺省与非法回退、supervisor 启动失败熔断（daemon 运行态语义的回归点；出处 tests/test_stale_code_selfheal.py 任务覆盖矩阵） | pass | 0/3 | - |
| cli-docs-config-section | docs/help/09-config.md 含 stale_code_selfheal 配置节说明（含两键与缺省值；出处 docs/help/09-config.md:203） | pass | 0/3 | - |
| cli-docs-safeguards-section | docs/help/07-safeguards.md 含代码陈旧自愈与启动失败熔断语义章节（含 restart_request / supervisor_fused 与人工恢复路径；出处 docs/help/07-safeguards.md:91） | pass | 0/3 | - |
| cli-docs-dashboard-section | docs/help/08-dashboard.md 设置页说明含「自愈」面板与 stale_code_selfheal 节（界面契约；出处 docs/help/08-dashboard.md:55） | pass | 0/2 | - |
| web-save-idle-roundtrip-300 | 设置页「自愈」页签修改 idle_confirm_seconds=300 保存：保存成功提示 + 离场重挂载后表单回显 300（设置页可读写写回配置文件；navigate 出处 app.tsx:111，面板 testid 出处 StaleCodeSelfhealPanel.tsx:98,117；依赖 web-panel-defaults-display 先行确认缺省展示） | pass | 0/5 | - |
| web-restore-idle-default-120 | 设置页「自愈」页签将 idle_confirm_seconds 复原为 120 保存：保存成功提示 + 离场重挂载后表单回显 120（复原缺省，避免残留 300 影响后续场景初始态；navigate 出处 app.tsx:111，面板 testid 出处 StaleCodeSelfhealPanel.tsx:98,117） | pass | 0/5 | - |
| web-enabled-toggle-roundtrip | 设置页「自愈」页签切换 enabled 开关为关→保存→离场重挂载回显 aria-checked=false（配置关闭路径的界面往返；navigate 出处 app.tsx:111，开关 testid 出处 StaleCodeSelfhealPanel.tsx:67；依赖 web-restore-idle-default-120 先行复原 idle=120） | pass | 0/6 | - |
| web-restore-enabled-default-on | 设置页「自愈」页签将 enabled 开关复原为开→保存→离场重挂载回显 aria-checked=true（复原缺省，避免残留 enabled=false 影响后续运行；navigate 出处 app.tsx:111，开关 testid 出处 StaleCodeSelfhealPanel.tsx:67） | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 新增场景 web-restore-enabled-default-on（重新规划，第 1 轮）
- 新增场景 web-restore-idle-default-120（重新规划，第 1 轮）

