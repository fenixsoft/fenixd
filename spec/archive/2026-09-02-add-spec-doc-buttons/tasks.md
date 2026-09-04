## 1. 后端 API

- [x] 1.1 在 `core/dashboard/data.py` 新增 `get_spec_doc(project_root, spec, doc) -> dict`：校验 spec 为 kebab-case、doc 属于 `{proposal, design}` 白名单；读取 `openspec/changes/<spec>/<doc>.md`，文件不存在返回 `{"found": False, "content": ""}`；解析后路径必须仍在 `openspec/changes/` 下，越界抛错
- [x] 1.2 在 `core/dashboard/server.py` 新增 `/api/spec-doc` 路由（置于 `/api/specs/` 分支之前或独立判断）：解析 query 参数，spec 非法/不在项目 STATE.md 返回 404，doc 非法返回 400，正常返回 `{found, content}` JSON
- [x] 1.3 更新 `server.py` API 文档注释（文件头路由清单）加入 `/api/spec-doc` 说明

## 2. 前端列表行按钮

- [x] 2.1 在 `app.js` 的 `specRow()` 中于操作单元格新增「背景」「设计」两个小按钮，`onclick` 调 `event.stopPropagation()` 后打开文档弹窗（分别传 `proposal` / `design` 与 spec 名称）
- [x] 2.2 `index.html` 增加文档弹窗容器（遮罩 + 头部（标题/关闭）+ 滚动 body），样式复用 runmodal 的 CSS 类（`.runmodal` `.runmodal-box` 等）
- [x] 2.3 `style.css` 增加 doc 按钮样式（紧凑行内按钮，不破坏表格布局）与弹窗正文 markdown 排版间距

## 3. 文档弹窗逻辑

- [x] 3.1 在 `app.js` 新增 `openDocModal(project, spec, doc)`：构建请求 `/api/spec-doc?project=&spec=&doc=`，加载中显示占位，成功后用 `md()` 渲染正文并标题显示「背景/设计」
- [x] 3.2 `found=false` 时展示空态文案（"该 spec 未提供背景/设计文档"）；请求失败（非 200/404、网络错误）显示错误提示而非空白
- [x] 3.3 弹窗支持关闭按钮、点击遮罩关闭；关闭后清空正文，列表页状态不变

## 4. 验证

- [x] 4.1 启动仪表盘，打开某含 proposal.md 与 design.md 的项目视图：每行可见两个按钮，点「背景」弹窗渲染 proposal 的 Markdown，点「设计」渲染 design 的 Markdown，点行其他区域仍进详情
- [x] 4.2 构造缺失文档的 spec（或临时改名文件）：按钮仍可见，点击显示空态文案
- [x] 4.3 手工请求 `/api/spec-doc`：非法 `doc` 返回 400，非法/不存在 spec 返回 404，`spec=../../etc/passwd` 返回 404 且不泄露文件内容
- [x] 4.4 回归：项目概览、SPEC 列表、详情页、运行弹窗等既有功能不受影响