## Context

Web 仪表盘（`core/dashboard/`）的 SPEC 列表页（`#project/<name>`）以表格展示项目内全部 SPEC 的状态、进度、创建时间等摘要，由 `specRow()` 渲染，点击行进入详情视图。当前没有任何入口查看 SPEC 的 `proposal.md` 与 `design.md` 这两份核心文档。

技术底座：
- 后端为 `http.server` 纯标准库实现（`server.py`），数据层为以 `project_root` 为参数的纯函数（`data.py`）。
- SPEC 的文档文件位于 `{project_root}/openspec/changes/<spec_name>/{proposal.md|design.md}`（与 `parse_tasks`/`count_scenarios` 相同的定位模式）。
- 前端已 vendored `marked`（`app.js` 1111-1130 行），`md(text)` 包装负责 GFM 渲染、链接白名单与转义；已有 `runmodal` 弹窗组件与样式可参考。

需求（用户确认）：按钮放在每行 SPEC 行内；点击在当前页 Modal 展示；按钮常显，文档缺失显示空态提示。

## Goals / Non-Goals

**Goals:**
- 每个 SPEC 行提供「背景」「设计」两个按钮，一键查看 proposal.md / design.md。
- 文档以 Markdown 渲染在弹窗中，复用现有渲染器与视觉，不引入新依赖。
- 文档缺失时用户得到清晰的空态反馈，而不是 404 错误。
- 保持行点击进入详情的既有交互不受影响。

**Non-Goals:**
- 不做文档编辑、预览窗口内的标题锚点跳转、目录折叠。
- 不在详情页（`#spec/...`）新增页签（用户已确认走列表页 Modal）。
- 不提供文档的 last-modified 等元信息接口。
- 不处理 worktree 中 in-progress spec 的文档回退读取（改动级 spec 目录为唯一文档源）。

## Decisions

**D1: 新端点 `GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design>`**

路径不与现有 `/api/specs/...` 路由前缀冲突（`/api/spec-doc` 不会被 `/api/specs/` 分支截获）。`doc` 用白名单校验（仅 `proposal` / `design`），非法值返回 400。

备选：`/api/specs/<spec>?doc=...` 扩展现有详情端点 —— 但详情端点语义是聚合运行时数据，混入文档会破坏既有消费方，故不采用。

**D2: 缺失返回 `{found: false}`（200）而非 404**

按钮常显策略下，文件缺失是常态分支而非异常：返回 `{found: false, content: ""}`，前端展示空态提示。仅当 `spec` 名称不在该项目 STATE.md 中时才返回 404。

**D3: 文档读取以解析后路径严格限制在 changes 目录内**

`spec` 参数按 `^[a-z0-9][a-z0-9-]*$` 校验，读取路径 `Path(project_root)/openspec/changes/<spec>/<doc>.md` 解析后必须仍在 `openspec/changes/` 之下（防御 `..` 拼接），防止任意文件读取。

**D4: 按钮 `stopPropagation` 阻止行跳转**

按钮在 `<td>` 内，行 `<tr onclick="nav(...)">` 会冒泡捕获点击。按钮的 `onclick` 中调用 `event.stopPropagation()`，保证点按钮只看文档、点行才进详情。

**D5: 复用 runmodal 的弹窗骨架，独立 docmodal 样式类**

runmodal 已具备遮罩、头部、关闭按钮、滚动 body 的结构。新建 `docmodal` 不混用 runmodal 的 run_id/SSE 事件绑定逻辑，仅复用视觉模式（`runmodal-box` 等 CSS 类可直接复用，语义独立）。

**D6: 正文用现有 `md()` 渲染，不做二次清洗**

`md()` 已带链接白名单与渲染器约束，与详情页共用同一渲染管线。文档来源是本机 `openspec/changes` 受控目录，风险面与详情页一致。

## Risks / Trade-offs

- [spec 参数可被构造为路径穿越] → D3 双重校验（kebab 正则 + resolved 路径前缀检查），并有对应 Scenario 测试。
- [大文档渲染卡顿] → 弹窗 body 已有 `overflow-y: auto`；文档通常数百行以内，可接受。不引入分页。
- [按钮与行点击误触] → D4 `stopPropagation`。
- [合并/归档后文档位置漂移] → 归档目录（`archive/`）当前不存在；若未来引入归档，spec 摘要端需同步返回文档定位信息，属后续增强，当前 state 驱动不阻塞。

## Migration Plan

纯增量前端 + 新增 API 端点，无破坏性变更，无需迁移。回滚 = 删除新端点与按钮/Modal 代码。

## Open Questions

无（交互方案已经用户确认）。