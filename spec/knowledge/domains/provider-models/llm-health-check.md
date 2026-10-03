<!-- knowledge: capability=llm-health-check rev=1 sources=spec/archive/2026-10-04-add-provider-health-check -->

# LLM Provider 健康检测（手动探测）

设置页一键验证「某 Provider+模型组合当前能不能回复、多快」的诊断通道：手动点击触发、daemon 后端代理执行、纯探测无副作用。与运行期模型链健康探测（[model-chain-health-probe](model-chain-health-probe.md)）互不相连——本能力只服务人工排障，不参与 failover。

## 规则

- 探测端点为 `POST /api/config/llm-health-check`，入参显式三字段 `{baseurl, apikey, model}`；端点不做 provider 名解析——provider 双源解析与模型解析链全部在前端完成，后端保持无状态纯探测。任一字段缺失或空串时回 HTTP 400 并指明缺失字段，不发起上游请求。
- 探测请求发往 `{baseurl}/v1/messages`（baseurl 去尾部 `/`，尾部 `/v1` 一并归一，避免拼出 `/v1/v1/messages` 的误导性 404），为 Anthropic 兼容最小消息：`role: user`、`content: "hello"`、`max_tokens: 256`。请求头 `x-api-key` + `anthropic-version: 2023-06-01`，apikey 非空时附加 `Authorization: Bearer`；User-Agent 与运行期 claude CLI 同签名——urllib 默认 UA 会被 Cloudflare 反爬按签名误拦（error code 1010）掩盖真实业务错误。
- `max_tokens` 必须给足正文余量且带 thinking 兜底：思考型模型（GLM/DeepSeek 系网关侧默认开思考）会把小预算全部耗在 thinking 块上；正文为空但 thinking 块非空时按成功处理。显式传 `thinking: disabled` 不可行（部分网关静默忽略或直接 400），不采用。
- 超时为 15 秒，单源定义于探测模块常量（`HEALTH_CHECK_TIMEOUT_SECONDS`），同步请求直传。
- 失败按四分类返回，探测失败也是业务数据（端点自身恒回 200 自含结果）：`http_error`（上游非 200，透传 status + 响应片段截断 ≤200 字符）、`connection_error`（连接被拒、DNS 失败、baseurl 非法、上游 HTTP 协议异常、提前断流）、`timeout`（15 秒未返回）、`empty_reply`（200 但解析不到非空文本 content，含响应非合法 JSON、响应体超 1 MiB 读取上限）。`latency_ms` 恒为实测毫秒（下限钳 1）；成功返回 `ok: true` 并回显请求的 model，失败不回显 model。
- 探测纯只读、零副作用：不落盘 apikey 与完整响应内容；MUST NOT 写入 provider 熔断计数、切换冷却或半开探针状态（见 [provider-fault-fuse](provider-fault-fuse.md)）——手动点检与运行期熔断彼此独立，点检不得把 provider 打入冷却。
- 安全边界：baseurl 由表单直传属不可信输入——拒绝跟随跨主机重定向（防探测密钥发往第三方主机，同主机重定向放行）；200 响应体设 1 MiB 读取上限，超限按 `empty_reply` 归类。端点不新增鉴权（dashboard 仅绑定 127.0.0.1，与既有无鉴权 POST 端点同面）。
- 入口两处、按钮形态统一为图标按钮（心形 HeartOutlined + title/aria-label「健康检测」）：「模型」页签每张 Provider 卡片标题栏删除图标左侧；「模型分配」页签每个 Provider 行删除图标之前的 32px 图标列。
- 表单当前值语义：「模型」页签用该卡片正在编辑的值直接检测（含未保存修改，无需先保存）；Base URL / API Key / 默认模型名任一为空时仅提示补齐、不发请求。
- 「模型分配」行按运行期同款链解析检测目标：模型 = 行内模型 → 角色级默认模型 → 所选 Provider 默认模型；baseurl/apikey 按行内所选 Provider 名先查表单正在编辑的 Provider 列表、查不到回退已保存配置（当前作用域）。解析不出任一字段时提示指明原因、不发请求，其它行不受影响。
- 结果展示两处共用同一口径：成功绿色「正常 · X.Xs」（秒一位小数）加成功 message；失败红色「失败 · <error_kind>」加 tooltip 完整错误与失败 message。组件本地仅保留最近一次结果，重新点击覆盖。
- 防重复：检测进行中按钮禁用（含同帧双击重入守卫）；「模型分配」状态与结果按行隔离，单行检测不影响其它行。
- 行内检测结论是特定 provider+模型组合的一次性结论：行内改选 Provider 或生效模型变化即清除该行结果，防旧徽标错配误导。
- 仅手动触发：不做周期/后台自动巡检，不做历史耗时曲线与多模型批量检测。

## 关键行为

点击 → 前端解析/校验（表单当前值或行内解析链，失败即提示不发请求）→ service `checkLlmHealth` 调后端端点 → 后端无状态探测并按四分类返回 → 前端内联展示结果与 message。

## 溯源

- 2026-10-04 2026-10-04-add-provider-health-check（spec/archive/2026-10-04-add-provider-health-check） — 新增本能力：后端无状态探测端点（最小请求、耗时测量、失败四分类、15s 超时、缺参 400）、前端 service 与解析链纯函数、两页签入口（表单当前值语义、行内状态隔离、内联结果展示）
- 归档后经实测修正（无对应归档目录，纯文本记）：探测 `max_tokens` 定格 256 并加 thinking 兜底、UA 与运行期 CLI 同签名、模型页签按钮由文字形态统一为图标、增设跨主机重定向拦截与响应体读取上限
