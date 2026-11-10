## Deliverables

```yaml
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/utils/agentModels.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QuickAssignModal.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/tests/agentModels.test.mjs
  kind: modify
- path: core/dashboard/static/tests/quickAssign.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端数据层（config_admin.py）

- [x] 1.1 新增模块级公开函数 `quick_assign_models(assignment, targets, source_scope) -> dict`（供 settings_routes 调用；targets/source_scope 已由路由层解析为 `{"scope":"user"}` 或 `{"scope":"project","project":<name>,"root":<项目根路径>}`）：以 `ConfigLoader.KNOWN_AGENT_TYPES` 全部角色生成同一份 `{model?, provider:[...]}` 深拷贝（角色级 model 为空则不写）并经 `ConfigLoader.serialize_models_patch` 规范化；用户级目标同样在 `quick_assign_models` 持 `_CONFIG_WRITE_LOCK` 的临界区内以 `{"agents":{"models": ...}}` 调 `_write_config_locked(None, patch, scope="user")`（该函数契约要求调用方已持锁，见 config_admin.py `_write_config_locked` docstring）；项目级目标持 `_CONFIG_WRITE_LOCK` 读项目 raw `llm.providers`，算出模板引用相对项目既有定义的缺失集合，从 source_scope 的有效 provider 定义按 name 复制补齐（保留项目既有同名定义、绝不覆盖），无法补齐则该项目单独失败（错误文本含缺失 provider 名），否则以含 `{"llm":{"providers":[...]}}`（仅补齐时携带）+ agents.models 的 patch 调 `_write_config_locked(root, patch, scope="project")`；逐目标收集 `{"scope","project"?,"ok","error"?,"path"?}`，单目标失败不中断其他目标，返回 `{"ok": all(result.ok), "results": [...]}`。复用既有校验/原子写，不另写 YAML 落盘逻辑。
- [x] 1.2 新增源 provider 定义解析辅助（如 `_source_provider_defs(source_scope)`）：用户级取用户级 raw `llm.providers`，项目级取 `read_effective_config(root)` 的 `llm.providers`；对非 dict 段、缺 name 元素做安全降级（忽略，交由 `_validate_merged_view` 兜底），确保不抛未捕获异常、不因源配置缺失导致 500。

## 2. 后端端点与路由注册

- [x] 2.1 `core/dashboard/routes/settings_routes.py` 新增 `_api_config_quick_assign(self, query)`（mixin 方法，仿 `_api_config_post`）：`body = self._read_json_body()`，None 直接 return（已回 400）；请求级校验——body 为 dict、`assignment` dict 且 `provider` 非空 list（每行 dict、`provider` 非空 str、`model` 缺省或 str）、`targets` 非空 list（元素 `scope` 为 `user` 或 `project`；project 目标 `project` 非空且 `self.server.project_by_name(name)` 解析到且 `exists`）、`source_scope` 同校验（project 才解析）；非法一律 `self._error(400, msg)` 且不调用数据层；目标按 `(scope, project)` 去重；解析 project 目标 root 后调 `dashboard_data.quick_assign_models(...)`，`self._json(result)`（执行含部分失败恒 200）。
- [x] 2.2 `core/dashboard/routes/base.py` 注册：新增适配函数 `_post_config_quick_assign(s, p, q, m) → s._api_config_quick_assign(q)`，并在 `_API_POST_ROUTES` 中 `/api/config/sync-from-user` 附近加 `("exact", "/api/config/quick-assign", _post_config_quick_assign)`。

## 3. 后端测试

- [x] 3.1 `tests/test_dashboard_data.py` 新增快速分配数据层用例（沿用文件既有 tmp 项目/配置 fixture；monkeypatch `core.dashboard.data.USER_CONFIG_PATH` 到 tmp）：① 用户级目标覆盖全部 13 角色、原各角色分配被替换、`subagent_model_override` 与其他 agents/llm 键保留、单行无元素级模型写为 provider 字符串形态；② 项目目标缺 provider 时补齐完整定义（name/baseurl/apikey/model/sdk_model）、项目既有 provider 与 llm 其他键保留；③ 项目已有同名 provider 定义不被覆盖；④ 模板引用的 provider 在 source 中不存在 → 该项目结果失败且配置文件未被写入，其他目标成功（部分成功语义）；⑤ 多行候选链顺序与元素级 model 保留、角色级缺省 model 仅在填写时写入。
- [x] 3.2 `tests/test_dashboard_api.py` 新增 `TestConfigQuickAssignAPI`（仿 `TestConfigSyncFromUserAPI` 的 `_make_server` / `srv.post_json` 模式）：POST `/api/config/quick-assign` 用户级成功 200 + 读回配置断言；两个项目目标其中一个失败仍 200 且 `results` 逐项含 ok/error、成功目标已落盘；`assignment` 缺省/provider 为空 list/targets 空/`targets` 中 project 未注册/`source_scope` 项目未注册 → 400 且无任何写入；未知路由路径返回 404（确认路由已注册）。

## 4. 前端服务层与纯函数

- [x] 4.1 `core/dashboard/static/src/services/dashboard.ts` 新增类型 `QuickAssignTarget`（`{scope:'user'} | {scope:'project'; project:string}`）、`QuickAssignAssignment`、`QuickAssignResult`（含 `scope/project?/ok/error?/path?`）、`QuickAssignResponse`（`{ok:boolean; results:QuickAssignResult[]}`）与 `quickAssignConfig(payload): Promise<QuickAssignResponse>`，POST `/api/config/quick-assign`，沿用 `request<T>`（非 2xx 抛 ApiError）。
- [x] 4.2 `core/dashboard/static/src/utils/agentModels.ts` 新增纯函数（零 React 依赖，保持可被 `node --test` 直接加载）：`buildQuickAssignAssignment(roleModel: string, rows: ChainRow[]): QuickAssignAssignment`（trim 输入；丢弃 provider 为空的行；model 留空则省略该字段；数组保持行序）与 `buildQuickAssignTargets(includeCurrent: boolean, project: string | undefined, selectedProjects: string[]): QuickAssignTarget[]`（本作用域按 project 有无展开为 user/project 目标；指定项目去重并剔除空串；本作用域目标在前）。

## 5. 弹窗组件与面板接入

- [x] 5.1 新建 `core/dashboard/static/src/pages/settings/components/QuickAssignModal.tsx`：props `{open, project?, projects: string[], providers: LlmProvider[], onCancel, onApplied(result)}`；`Modal`（title「快速分配」、footer 取消/应用、saving 时 loading + disabled 防重入）；模板编辑器为角色默认模型 `Input` + 候选链行列表（provider `Select` options 为 providers 名称、model `Input`、删除行/新增行按钮，至少保留一行）；作用域区为「本作用域」`Checkbox`（默认勾选，标签显示「用户级」或「项目 <名称>」）+「指定项目」`Checkbox` 联动 `Select mode="multiple"`（options=projects）；无有效 provider 行或无目标时应用按钮 disabled；应用时先构造 payload（`buildQuickAssignAssignment` / `buildQuickAssignTargets` 构造 assignment/targets，`source_scope` 按当前设置页作用域构造：用户级 `{"scope":"user"}`、项目级 `{"scope":"project","project":<当前项目>}`，必填，见 design D2），若目标含本作用域且 `anyPanelDirty()`（从 `../panelDirty` 引入）则 `Modal.confirm` 提示「快速分配将覆盖全部角色的模型分配，并丢弃当前未保存的修改」、取消则中止，然后调 `quickAssignConfig`；结果逐项展示（全部成功提示成功目标数；存在失败逐项列出目标与原因，不得只报成功）。
- [x] 5.2 `core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx`：新增 props `projects: string[]`、`onQuickAssignApplied: (result: QuickAssignResponse) => void`；在 `<h3>模型分配</h3>` 标题行右侧放「快速分配」按钮（antd `Button` small 档），点击打开弹窗，弹窗传入 `project`、`projects`、`providers=config.llm.providers` 与关闭/应用回调。
- [x] 5.3 `core/dashboard/static/src/pages/settings/index.tsx`：向 `AgentModelPanel` 传 `projects`（已加载项目名列表）与新增 `handleQuickAssignApplied(result)`：若 `results` 含本作用域成功项（`scope==='user'`，或 `scope==='project'` 且 `project===scope` 当前项目）→ 同步 `snapshotPanelDirty()` → `getConfig(project)` 重载（沿用 scopeRef/projectRef 币值守卫）→ `setConfig`，重载失败沿用既有「已保存，但刷新配置失败…」warning 文案；若仅指定项目成功则只提示成功、不重载当前表单；成功提示包含「配置已保存，重启 daemon 后生效」。

## 6. 前端测试与生产构建

- [x] 6.1 `core/dashboard/static/tests/agentModels.test.mjs` 增加 `buildQuickAssignAssignment` / `buildQuickAssignTargets` 用例：空行过滤、trim、model 留空省略、provider 为空行丢弃；本作用域展开（user / project）、指定项目去重与空串剔除、顺序（本作用域在前）。
- [x] 6.2 新建 `core/dashboard/static/tests/quickAssign.test.mjs`：沿用 `tests/hooksPanel.test.mjs` 的 esbuild 打包 + `react-dom/server` SSR 范式（react/react-dom/antd external，产物落 `node_modules/.tmp-*`，无 jsdom）渲染 `QuickAssignModal`，断言标题、模板行控件、本作用域/指定项目选项、应用按钮在场及禁用态；另断言源码中无新增 CSS 动画/过渡（DESIGN.md 静态渲染约束）。
- [x] 6.3 前端验证：`cd core/dashboard/static && node --test tests/*.test.mjs` 全量通过，并 `npm run build` 重建生产产物（`dist/` 为 gitignored 构建产物，不纳入交付声明，无需提交）。
- [ ] 6.4 移动端形态自检：在 390px 视口下打开弹窗（可用既有 playwright 测试环境或 SSR 断言 + 源码检查），确认弹窗 body 可滚动、应用/取消按钮可达、无横向溢出；截图/临时文件放 `.history/`。

## 7. 回归

- [x] 7.1 后端相关测试全通过：`python3 -m pytest tests/test_dashboard_data.py tests/test_dashboard_api.py tests/test_provider_ref_validation.py tests/test_config.py tests/test_agent_prompt_files.py -q`（单用例 10s 超时门禁，超时按 `tests/timeout-allowlist.yaml` 规范处理）。
