# v3 SPEC 文档弹窗（spec-doc-view）

## ADDED Requirements

### Requirement: 三页签文档加载

「文档」弹窗提供需求背景（proposal）/ 详细设计（design）/ 任务清单（tasks）三个页签；页签首次激活时经 `GET /api/spec-doc?project=<name>&spec=<name>&doc=<key>` 懒加载对应文档，加载结果按 spec+doc 键缓存在组件内，再次切换不重复请求。

#### Scenario: 首次打开并切换页签

- **WHEN** 用户点击某 spec 的「文档」打开弹窗并依次切换三个页签
- **THEN** 每个页签首次激活时各发起一次 `/api/spec-doc` 请求，回切已看过的页签不再发起请求

#### Scenario: 弹窗关闭后重新打开

- **WHEN** 用户关闭弹窗后再次点击同一 spec 的「文档」
- **THEN** 已缓存的页签内容立即展示，不重新请求（语义同 v1 docCache）

### Requirement: Markdown 渲染

文档 content 以 Markdown 渲染为富文本，支持 GFM 常用语法（标题、列表、表格、代码块、任务勾选、链接、行内样式）；链接仅放行 http/https/mailto 协议，其余协议不渲染为可点击链接（对齐 v1 安全渲染策略）。

#### Scenario: GFM 语法渲染

- **WHEN** 任务清单文档包含标题、任务勾选列表与表格
- **THEN** 弹窗内渲染出对应层级的标题、可勾选样式的列表项与表格，而非 Markdown 原始符号

#### Scenario: 链接协议白名单

- **WHEN** 文档中包含 `javascript:` 或其它非 http/https/mailto 协议的链接
- **THEN** 该链接不渲染为可点击的 `<a>`（渲染为纯文本或被移除 href）

### Requirement: 空态与错误态

文档不存在（响应 `found: false`）时展示明确的"无此文档"空态；请求失败时展示错误态并允许重试（重新打开弹窗或切换页签可再次触发加载）；加载中展示加载态。三种状态不得渲染为空白。

#### Scenario: 无此文档

- **WHEN** 某 spec 缺少 design.md（`found: false`）
- **THEN** 「详细设计」页签展示"无此文档"类空态，其余页签不受影响

#### Scenario: 加载失败重试

- **WHEN** 文档请求失败后用户切换页签再切回
- **THEN** 触发重新加载并展示加载态，成功后渲染内容
