# Tasks: Dashboard SPEC 列表 —— 文档入口整合为三页签弹窗 + 信息行紧凑化与清除

## 1. 后端：spec-doc 白名单扩展 tasks

- [ ] 1.1 `core/dashboard/data.py`：`_SPEC_DOC_WHITELIST` 扩展为 `("proposal", "design", "tasks")`，同步 `InvalidSpecDoc` 文案与 `get_spec_doc` docstring
- [ ] 1.2 `core/dashboard/server.py`：`_api_spec_doc` docstring 端点说明更新为 `<proposal|design|tasks>`

## 2. 后端：清除 error 端点

- [ ] 2.1 `core/dashboard/data.py`：新增 `clear_spec_error(project_root, spec)` 函数——校验 spec 存在后实例化 `StateMachine(proot / "STATE.md")` 调用 `update_spec(spec, {"error": None})`，返回 `{ok}`；spec 缺失返回 `{found: false}`
- [ ] 2.2 `core/dashboard/server.py`：新增 `POST /api/spec-error-clear?project=<name>&spec=<name>` 路由——project/spec 校验同 `_api_spec_doc`（不存在 404），成功 200 `{ok: true}`，调用异常时 500
- [ ] 2.3 `tests/test_dashboard.py`：新增用例——`doc=tasks` 读取成功/缺失空态/既有分支不回归；清除端点成功（`error` 置空且其余字段不变）、spec 不存在 404、项目不存在 404

## 3. 前端：信息子行布局修复 + 清除按钮

- [ ] 3.1 `core/dashboard/static/app.js`：信息子行渲染改为标签与内容源码同行的 flex 结构，badge 后不换行；子行尾部追加「清除」按钮（`stopPropagation`），点击调 `POST /api/spec-error-clear`，成功不额外处理（2 秒轮询/SSE 自动刷新），失败行内错误提示
- [ ] 3.2 `core/dashboard/static/style.css`：`.spec-info-row td` 改 `display: flex; align-items: flex-start`；`.info-badge` 不换行固定；`.info-msg` 独立 `white-space: pre-wrap; word-break: break-word; min-width: 0; flex: 1`；新增清除按钮样式

## 4. 前端：文档列整合 + 三页签弹窗

- [ ] 4.1 `core/dashboard/static/app.js`：`specRow` 文档列由两按钮改为单个「文档」链接（`stopPropagation` 保留）
- [ ] 4.2 `core/dashboard/static/app.js`：`openDocModal` 重构为三页签窗口——默认激活「需求背景」并加载；页签切换按需加载 + `(project, spec, doc)` in-flight/结果缓存（复用 `fetchWhy` 模式）；`DOC_LABELS`/`DOC_EMPTY_TEXT` 扩展 `tasks`（「该 spec 未提供任务清单文档」）
- [ ] 4.3 `core/dashboard/static/index.html`：`docmodal` 增加页签容器与页签按钮
- [ ] 4.4 `core/dashboard/static/style.css`：弹窗页签栏样式（激活态、hover），响应弹窗宽度下可读

## 5. 回归验证

- [ ] 5.1 运行 `python3 -m pytest tests/test_dashboard.py -q`（既有 spec-doc 各分支 + 新增用例全绿）
- [ ] 5.2 启动 dashboard，手工验证：信息行标签与内容同行；短/长消息（含内部换行）显示正确；点击清除后子行消失、`STATE.md` `error` 置空；「文档」链接打开三页签，三份文档分别渲染、缺失页签空态、网络失败错误态；点链接/清除不跳详情、点行空白仍跳详情

## 6. 收尾

- [ ] 6.1 更新 `core/dashboard/server.py` 头部端点清单注释（新增 `POST /api/spec-error-clear`、`doc` 白名单扩展）
- [ ] 6.2 确认无 `background|design` 双按钮残留调用（grep `openDocModal` 仅剩弹窗内部页签加载路径）