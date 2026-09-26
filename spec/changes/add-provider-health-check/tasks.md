## Deliverables

```yaml
- path: core/dashboard/llm_health.py
  kind: new
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/utils/llmHealth.ts
  kind: new
- path: core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx
  kind: modify
- path: tests/test_llm_health.py
  kind: new
- path: core/dashboard/static/tests/llmHealth.test.mjs
  kind: new
```

## 1. 后端探测模块

- [ ] 1.1 新建 `core/dashboard/llm_health.py`：`run_llm_health_check(baseurl, apikey, model) -> dict`，对 `{baseurl 去尾斜杠}/v1/messages` 发最小消息请求（`role: user` / `content: "hello"` / `max_tokens: 64`；请求头照抄 `bin/probe_prompt_cache.py` 先例：`x-api-key` + `anthropic-version: 2023-06-01` + apikey 非空时 `Authorization: Bearer`，stdlib urllib 不引入新依赖）；模块级常量 `HEALTH_CHECK_TIMEOUT_SECONDS = 15`；返回 `{"ok", "latency_ms", "error_kind", "status", "error", "model"}`（`model` 仅成功时回显请求的 model，与 spec「模型正常回复」Scenario 对齐；失败场景按 spec 对应响应体取值），失败四分类 `http_error`（非 200，带 status + 响应片段截断 ≤200 字符）/ `connection_error` / `timeout` / `empty_reply`（200 但解析不到非空文本 content）；函数内不落盘 apikey 与完整响应。
- [ ] 1.2 新建 `tests/test_llm_health.py`：monkeypatch urllib 替身覆盖 200 正常回复（latency_ms 为正整数、model 回显口径）、非 200（error_kind=http_error + status 透传 + 片段截断）、超时（error_kind=timeout）、连接异常（error_kind=connection_error）、200 无文本（error_kind=empty_reply）、baseurl 尾斜杠去除；`pytest tests/test_llm_health.py` 全绿。

## 2. 端点接线

- [ ] 2.1 `core/dashboard/routes/settings_routes.py` 新增 `_api_config_llm_health_check_post(query)`：`_read_json_body` 读 body，`baseurl`/`apikey`/`model` 缺一或空串时 `_error(400, 指明缺失字段)` 不发上游请求；合法时调用 `run_llm_health_check` 并 `_json` 自含返回（探测失败也是 200 业务数据，见 spec「上游返回 HTTP 错误」Scenario）。
- [ ] 2.2 `core/dashboard/routes/base.py`：新增 POST 适配函数 + 在 `_API_POST_ROUTES` 注册 `("exact", "/api/config/llm-health-check", ...)`。

## 3. 前端 service 与解析工具

- [ ] 3.1 `core/dashboard/static/src/services/dashboard.ts` 新增 `checkLlmHealth(params: { baseurl; apikey; model })` service 函数，走既有 `request()` 封装并导出结果类型。
- [ ] 3.2 新建 `core/dashboard/static/src/utils/llmHealth.ts`：`resolveHealthCheckParams({ formProviders, savedProviders, providerName, rowModel, roleModel })` —— 模型链＝行内模型 → 角色级缺省 → Provider 默认模型；baseurl/apikey 先按名查 formProviders（表单当前值）、查不到回退 savedProviders（已保存配置）；解析不出任一字段返回 `{ error: <原因> }`，纯函数零 React 依赖。
- [ ] 3.3 新建 `core/dashboard/static/tests/llmHealth.test.mjs`（node --test + 原生 type-stripping 导入 .ts，范式同 `agentModels.test.mjs`）：行内模型已填 / 留空走角色级缺省 / 再留空走 Provider 默认 / Provider 仅在已保存配置中（回退命中）/ 两处都无（返回 error）各分支。

## 4. 两页签入口与验证

- [ ] 4.1 `LlmProviderPanel.tsx`：每张 Provider 卡片标题栏删除图标左侧新增文字按钮「健康检测」；点击前校验该卡片 Base URL / API Key / 默认模型名非空（空则 message 提示补齐不发请求）；检测中按钮 loading 禁重复；结果内联显示在标题栏（成功绿色「正常 · X.Xs」+ 成功 message，失败红色「失败 · <error_kind>」+ 失败 message + tooltip 展示完整 error），表单当前值直传（未保存修改即测）。
- [ ] 4.2 `AgentModelPanel.tsx`：每个 Provider 行在删除图标列之前新增 32px 图标按钮列（icon-only、title/aria-label「健康检测」）；点击时用 `resolveHealthCheckParams` 解析（config.llm.providers 为表单当前值），解析失败 message 提示原因不发请求；按行隔离 loading 与结果 state（防行间串扰与并发重复），内联展示口径与 4.1 一致。
- [ ] 4.3 验证收口：`cd core/dashboard/static && npm run build` 通过、`npm test` 全绿；后端 `pytest tests/test_llm_health.py core/dashboard 相关既有 API 用例`（`tests/test_dashboard_api.py`）无回归。
