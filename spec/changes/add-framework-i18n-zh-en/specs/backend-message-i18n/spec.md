# 能力规格：backend-message-i18n（后端用户可见消息国际化）

## ADDED Requirements

### Requirement: 消息目录单源
core 层 SHALL 新增消息目录单源模块：以稳定消息键为索引的 zh/en 双语字典；`zh` 文本与现状存量文案保持一致，`en` 为对照翻译；查询不存在的 en 文本时 SHALL 回退返回 zh 文本，目录外未知键 SHALL 原样返回键本身以便暴露遗漏。

#### Scenario: 双语键查询与缺键回退
- **WHEN** 以 `en` 与 `zh` 分别查询同一存在键
- **THEN** 分别返回英文与中文文本；以 `en` 查询仅存在 zh 文本的键时返回该中文文本

### Requirement: 按请求 locale 解析
Dashboard 服务端 SHALL 按请求解析展示语言：读 `Accept-Language` 请求头，值域白名单为 zh 系与 en 系（前缀匹配），无头、无法解析或白名单外的值一律回退 `zh`；解析结果仅作用于该请求的展示型字符串，MUST NOT 影响其他请求与任何业务逻辑判定。

#### Scenario: 请求头决定消息语言
- **WHEN** 两个并发请求分别携带 `Accept-Language: en` 与不携带该头请求同一出错端点
- **THEN** 前者 `error` 字段为英文、后者为中文，二者业务语义与 HTTP 状态一致

### Requirement: 展示型字符串经目录输出
Dashboard API 面向用户展示的字符串 SHALL 经消息目录输出：API `error` 字段、状态/事件类展示标签（时间轴与处置链节点标签、Agent 展示标签、告警/自动运维记录的展示型描述等前端直接渲染的文本）。内部运行日志、调试日志、落盘产物文件内容 MUST NOT 经目录改造，保持中文现状。

#### Scenario: 错误响应双语化
- **WHEN** 以 en locale 请求引用不存在项目的展示型端点
- **THEN** 响应 `error` 字段为目录中的英文文本（不再是无对照的中文硬编码）

#### Scenario: 内部日志不受请求语言影响
- **WHEN** 以 en locale 发起任意 API 请求
- **THEN** daemon 运行日志该请求相关行仍为中文，语言为 zh 与 en 的两次请求日志内容一致

### Requirement: 前端请求层附带 locale
前端请求层 SHALL 在 API 请求统一附带 `Accept-Language` 头，取值为当前生效语言（zh 系/en 系映射）；语言切换后新发出的请求 SHALL 携带新值。

#### Scenario: 语言切换后请求头跟随
- **WHEN** 前端语言由中文切换为 English 后触发任一 API 轮询
- **THEN** 该请求携带 `Accept-Language: en`，页面展示的对应消息文本为英文
