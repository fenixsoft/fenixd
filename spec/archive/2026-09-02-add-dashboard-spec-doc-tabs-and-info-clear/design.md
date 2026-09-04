# Design: Dashboard SPEC 列表 —— 文档入口整合为三页签弹窗 + 信息行紧凑化与清除

## Context

Dashboard 项目视图 SPEC 列表当前状态：

- **信息子行**（`add-spec-list-hover-hint` 引入）：`default_spec_row` 在 `error` 非空时跨全列渲染信息子行。子行 `<td>` 设 `white-space: pre-wrap`，HTML 源码中 `</span>` 与 `<span class="info-msg">` 之间的换行符被保留渲染，导致「信息」标签与内容之间出现一个换行（`add-multi-project-monitoring` 可见）。子行无任何操作入口，`error` 需手动编辑 `STATE.md` 才能清除。
- **文档入口**（`add-spec-doc-buttons` 引入）：每行「背景」「设计」两个按钮分别打开单一文档弹窗；`GET /api/spec-doc` 的 `doc` 白名单 `{proposal, design}` 由 `data.py: _SPEC_DOC_WHITELIST` 与 `server.py: _api_spec_doc` 双重把关。`tasks.md` 与 `proposal.md` 同目录但无读取能力、无列表页入口。
- Dashboard server 为独立进程（`serve(registry)`），写 `STATE.md` 经 `StateMachine.update_spec` → `write_all`（flock 序列化 + tmp 原子 rename），与 daemon 并发写安全。watcher 监视 `STATE.md` mtime，写后自动 SSE 推送列表刷新。

## Goals / Non-Goals

**Goals:**
- 信息子行「信息」标签与内容同一行显示，短消息单行呈现，长消息内部换行保留且不破坏表格宽度。
- 提供「清除」按钮在线清理 `STATE.md` 的 `error` 字段，经既有 watcher 管道自动刷新列表。
- 「背景」「设计」两按钮整合为单个「文档」链接，弹窗承载「需求背景 / 详细设计 / 任务清单」三页签，内容按需懒加载。

**Non-Goals:**
- 不改变 `error` 字段的写入语义（Agent / 恢复流程照旧写入；清除是快照操作，不阻止后续写入）。
- 不做文档编辑、不做时间轴/详情页等其它视图的文档入口改造（本次仅列表页文档列）。
- 不引入新依赖（继续零新增依赖，前端仍内联在 `app.js` + vendored `marked`）。

## Decisions

### D1: 信息行布局修复 —— CSS 结构修复而非源码单行化

根因是 `<td>` 的 `white-space: pre-wrap` 保留标签与内容 span 之间的源码换行符。修复采用结构性方案：信息子行 `<td>` 改为 flex 容器（`display: flex; align-items: flex-start;`），「信息」badge 为不换行的固定元素，`.info-msg` 独立承担 `white-space: pre-wrap; word-break: break-word; min-width: 0;` 并 `flex: 1`。这样无论源码中标签与内容是否换行都渲染在同一行，且消息内部换行语义保留。渲染侧同时保持单行输出，双保险。

### D2: 清除端点 —— new `POST /api/spec-error-clear`，写回走 StateMachine

`POST /api/spec-error-clear?project=<name>&spec=<name>`：

- 校验与既有 `_api_spec_doc` 一致（project 存在、spec 在 `STATE.md`、名称 kebab-case），失败 404。
- 成功路径：实例化 `StateMachine(proot / "STATE.md")` 调 `update_spec(spec, {"error": None})`——复用其 flock + 原子 rename。不会与 daemon 并发写冲突（同一 `write_all` 语义）。
- 幂等：`error` 已为 `null` 时也返回成功（`update_spec` 会 refresh `updated` 时间戳，触发 SSE 刷新；可接受，且用户点击本就在信息子行可见时发生）。
- 后端在 `dashboard_spec_table` 能力规范中要求建立测试（spec 不存在 / 项目不存在 → 404，成功 → `error` 置空且其它字段不变）。

### D3: 弹窗三页签 —— 单弹窗 + 页签级懒加载缓存

保留 `docmodal`（复用 `runmodal` 视觉类）；头部标题为 SPEC 名称，正文顶部新增页签栏（`需求背景 / 详细设计 / 任务清单`）。每页签独立容器：

- 打开默认激活「需求背景」并立即加载。
- 切换页签时该页签若未加载则请求 `/api/spec-doc`（`doc=proposal|design|tasks`），in-flight 用 `(project, spec, doc)` 键合并（复用 `fetchWhy` 的 in-flight 缓存模式），已加载直接展示。
- `DOC_LABELS` / `DOC_EMPTY_TEXT` 扩展 `tasks` 项（「该 spec 未提供任务清单文档」）；文档缺失/加载失败按页签内空态/错误态呈现，不影响其它页签。
- 后端 `_SPEC_DOC_WHITELIST` 与文档字符串同步扩展 `tasks`（路径构造与既有一致：`changes/<spec>/tasks.md`，`..` 穿越校验不变）。

### D4: 清除按钮放置与交互

信息子行（flex 布局）尾部追加「清除」按钮（小尺寸、静默样式），点击 `stopPropagation` 防行跳转，调 `POST` 端点；成功依赖 watcher/2 秒轮询刷新（既有 2 秒自动刷新机制已存在，无需额外握手）；失败时按钮短暂显示错误提示（禁用态 + 行内提示），`STATE.md` 不变。

## Risks / Trade-offs

- **并发写覆盖窗口**：`StateMachine.write_all` 为全量重写、最后写者胜，清除操作理论上可能与 daemon 同时写入互相覆盖。既有架构（配置页保存、状态转换）同此模型，写窗口微秒级且清除操作稀少，沿用现模型不新增锁设施。
- **清除后端到端可见性**：清除依赖 watch 循环发现 `STATE.md` mtime 变化后推送；若 watcher 抖动，前端 2 秒轮询兜底刷新，行为不依赖单一通道。
- **页签首帧**：默认页签加载期间弹窗先行打开并显示加载占位（与既有弹窗行为一致），不阻塞列表交互。
- **`tasks.md` 读取面扩大**：仅扩展同一 changes 目录内文件，kebab-case + `..` 校验保持，攻击面无实质变化。