<!-- knowledge: capability=v3-spec-doc-view rev=1 sources=spec/archive/2026-09-08-improve-v3-spec-doc-markdown -->

# v3 SPEC 文档弹窗

v3 的 SPEC 文档查看：三页签懒加载 + Markdown 富文本渲染 + 三态（空态/错误态/加载态）区分。

## 现行规则

- 「文档」弹窗提供需求背景（proposal）/ 详细设计（design）/ 任务清单（tasks）三个页签；页签首次激活时经 `GET /api/spec-doc?project=<name>&spec=<name>&doc=<key>` 懒加载对应文档。
- 加载结果按 spec+doc 键缓存在组件内：已看过页签回切不重复请求；弹窗关闭后重新打开，已缓存内容立即展示、不重新请求。
- 文档 content 以 Markdown 渲染为富文本，支持 GFM 常用语法（标题、列表、表格、代码块、任务勾选、链接、行内样式）。
- 链接仅放行 http/https/mailto 协议；其它协议（如 `javascript:`）不渲染为可点击链接（渲染为纯文本或移除 href）。
- 三态并存且不得渲染为空白：文档不存在（`found:false`）→「无此文档」空态（仅影响对应页签）；请求失败 → 错误态并允许重试（切换页签或重开弹窗再次触发加载）；加载中 → 加载态。

## 溯源

- [2026-09-08 improve-v3-spec-doc-markdown](spec/archive/2026-09-08-improve-v3-spec-doc-markdown/) — 落地三页签懒加载与组件内缓存、GFM Markdown 安全渲染（链接协议白名单）及空态 / 错误态 / 加载态三态区分
