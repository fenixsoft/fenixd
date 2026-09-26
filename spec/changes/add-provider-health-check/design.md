## Context

- 「模型」页签 = `LlmProviderPanel.tsx`（Provider 卡片：名称 / Base URL / API Key / 默认模型名，标题栏 extra 现只有 Popconfirm 包裹的删除图标）。
- 「模型分配」页签 = `AgentModelPanel.tsx`（角色卡片 → Provider 行：拖拽手柄 / Provider 下拉 / 模型输入 / 删除图标，见 `AgentModelPanel.tsx:399` 附近的行布局）。
- 运行期 Provider 消费方式：claude CLI 经 `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` 走 Anthropic 兼容协议（`core/agent_runner/runner.py:1044`）。健康检测因此对 `{baseurl}/v1/messages` 发 Anthropic messages 请求即可代表真实可用性。
- 既有直连先例：`bin/probe_prompt_cache.py` 用 stdlib urllib 构造 `/v1/messages` 请求（`x-api-key` + `anthropic-version: 2023-06-01` + 条件 `Authorization: Bearer`）。
- Dashboard 路由形态：handler 写在 `routes/settings_routes.py` 的 `H5SettingsRoutesMixin`，经 `routes/base.py` 的 `_API_POST_ROUTES` 表 + 适配函数注册（exact 匹配）。

## Goals / Non-Goals

**Goals:**

- 一键判断「这个 Provider/模型组合当前能不能回复 + 多快」。
- 支持**未保存**配置的检测（表单当前值语义），配置完成后即可验证再保存。
- 模型分配行按运行期同款模型解析链检测（行内模型 → 角色级缺省 → Provider 默认）。

**Non-Goals:**

- 不做周期性/后台自动巡检（仅手动点击触发）。
- 不做历史耗时曲线、多模型批量检测。
- 不改动检测目标 Provider 之外的任何运行期行为；端点为纯探测，无副作用、不落盘密钥。

## Decisions

- **D1 后端代理执行，前端不直连**：浏览器直连任意 baseurl 受 CORS 限制且需把 apikey 暴露给页面运行时之外的网络路径；daemon 侧代理一次 HTTP 调用即可。替代方案（前端 fetch 直连）被否。
- **D2 新模块 `core/dashboard/llm_health.py` 承载检测逻辑**：handler 只做参数校验与响应编排；HTTP 探测独立成函数便于单测（monkeypatch 替换 urlopen）。请求构造照抄 `bin/probe_prompt_cache.py` 先例（stdlib urllib，不引入 requests 依赖；该脚本从 config 读 provider dict，本模块入参显式三字段）。
- **D3 端点入参为显式三字段（baseurl/apikey/model），不做 provider 名解析**：解析逻辑（表单 Provider 列表优先、回退已保存配置、模型解析链）全部在前端完成——前端本来就持有表单值；后端保持无状态纯探测，避免端点隐式依赖配置作用域。失败分类枚举：`http_error`（带 status）/ `connection_error` / `timeout` / `empty_reply`。端点自身对探测失败恒回 200（探测结果是业务数据），仅缺参 400。
- **D4 超时 15s 单源常量**：`core/dashboard/llm_health.py` 模块级 `HEALTH_CHECK_TIMEOUT_SECONDS = 15`；同步 urlopen(timeout=) 直传。检测是用户点击后的显式等待，15s 足够覆盖慢网关又不至于让页面干等过久。
- **D5 前端 service 层新增 `checkLlmHealth(params)`**：走既有 `request()` 封装；两处面板共用。
- **D6 模型分配行解析链在前端实现**：`baseurl/apikey` 先查表单 `config.llm.providers`（用户正在编辑的值，未保存修改即测语义），查不到名再回退 props 传入的已保存 `config` 同名字段；模型链 = 行内模型 → `roleModel` → Provider 默认模型。行布局加一列 32px 图标按钮（同删除列宽度），删除列保持不动——满足「在删除图标之前」。
- **D7 结果内联展示**：按钮旁（模型页签在标题栏、模型分配在行内）显示短结果文本 + tooltip 完整错误；组件本地 state 保存最近一次结果，重新点击覆盖。检测中按钮 loading/禁用防重复（模型分配按行隔离状态）。

## Risks / Trade-offs

- [探测请求消耗少量 token 计费] → `max_tokens: 64` + "hello"，单次成本可忽略；不自动重试。
- [同步端点占用 handler 线程最长 15s] → dashboard HTTP server 本就并发处理请求（keep-alive 线程模型）；15s 上限可控，不做异步化。
- [网关对 `/v1/messages` 路径变体（如带版本前缀的代理）行为不一] → 与 claude CLI 运行期同路径同协议，检测结论对运行期可用性有效；`connection_error`/`http_error` 分类足以指导排障。
- [表单当前值含未校验输入（如半截 URL）] → 后端按 `connection_error` 归类返回，前端原样展示；不做前端预校验 URL 合法性（避免误拦）。

## Migration Plan

纯新增，无迁移。回滚 = 移除新端点注册与两处按钮。

## Open Questions

（无——数据源、执行模式、执行时机均已与用户确认：表单当前值 / fast-track / 立即执行。）
