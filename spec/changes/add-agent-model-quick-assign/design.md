## Context

设置页「Agent 模型分配」页签当前为 13 个 Agent 角色（以 `ConfigLoader.KNOWN_AGENT_TYPES` 为准）逐卡编辑：每卡有角色级默认模型 + 多行 provider+模型候选链，卡片间只能通过复制/粘贴逐角色搬运。运维常见动作是「全部角色统一为同一组模型」（切换网关、灰度新模型、统一降级），逐角色操作成本高且易漏配，也无法一次投放到多个项目的项目级作用域。

既有配置体系约束（影响方案）：

- 分级配置：用户级 `~/.fenix/config.yaml` 与项目级 `<project_root>/.fenix/config.yaml` 深度合并，`llm.providers` 为列表段、合并时**整体替换**；设置页真实读写本仓库 `core/dashboard/data/config_admin.py`。
- 写入单源：`write_config` / `_write_config_locked` 持 `_CONFIG_WRITE_LOCK` 做读-改-写，`agents.models` 经 `ConfigLoader.serialize_models_patch` 规范化后整体替换，写前 `_validate_merged_view` 校验，最后原子写。
- **关键约束**：`_validate_merged_view` 的 provider 引用校验使用合并后的 `merged["llm"]`，而项目级写入路径的 `merged["llm"]` 只来自**项目级 raw config**，不包含用户级继承。目标项目只继承用户级 `llm.providers` 时，直接写项目级 `agents.models` 会被判「引用了不存在的 provider」而 400。
- 前端：面板判脏/回填由 `usePanelDirty`（`panelDirty.ts`）与 `useGatedFormPanel` 承担；配置页 `index.tsx` 负责作用域切换、保存、重载（含作用域币值守卫防迟到回包覆盖）。

设计约束以 `DESIGN.md`（界面设计宪法）为准（当前摘录：静态渲染、无动画/过渡/装饰动效；配色单源 `theme.ts`；字号阶 11/12/13/14/16/18/28；灰字 `colorTextTertiary`；空值显示「—」；移动端改布局不改宽度）。本设计**无偏离条款**，故不写偏离声明段。

需求见 `specs/llm-model-assignment/spec.md`（ADDED Requirements），动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 一次编辑模板（角色级缺省模型 + provider+模型候选链），整体覆盖全部已知 Agent 角色。
- 支持「本作用域」（当前设置页所选用户级/项目级）与「指定项目」（多选，逐项目写项目级）。
- 目标项目缺模板引用的 provider 定义时自动从当前作用域有效配置补齐，保留项目既有同名定义。
- 逐目标写入、逐项返回结果，单目标失败不影响其他目标。
- 本作用域写入成功后配置页重载并清除面板判脏；仅写指定项目时不打扰当前表单。
- 不改变配置格式、daemon 运行期模型解析与其他页签。

**Non-Goals:**

- 不做「快速分配模板预设/命名保存」的持久化（仅弹窗内临时模板）。
- 不批量修改 `agents.subagent_model_override`、并行度等其他 agents 键，也不改 `llm.providers` 之外的其他 llm 键。
- 不提供撤销/回滚快照（配置为明文 YAML，用户可手工回滚）。
- 不支持未在 dashboard 注册的项目名，也不做项目自动发现。
- 不改变 `llm-model-assignment` 既有单角色编辑行为。

## Decisions

### D1 新增专用后端端点 `POST /api/config/quick-assign`，而非前端循环调用既有 `POST /api/config`

理由：

1. 项目目标需要「先读目标项目 raw `llm.providers` → 判定缺失 → 构造含补齐定义的 patch → 写入」的读-改-写；项目级写路径的 provider 校验只看项目 raw，前端拿到的 `GET /api/config?project=` 是**有效合并视图**（项目未定义 providers 时显示的是用户级的），前端据此判断会得出错误结论。
2. 多目标写入必须在服务端统一做部分成功语义与逐项结果；前端 N 次请求难以在单次提交内保持 loading/防重入与一致的错误口径。
3. provider 定义来源由服务端从源作用域配置读取（见 D3），避免把含 `apikey` 的 provider 定义在请求里来回传输，也避免客户端伪造定义。

备选：前端复用 `POST /api/config?project=` 逐目标串行写，并在项目目标前额外请求读取项目 raw 配置 —— 需新增读取端点或误用有效视图，请求数多、错误语义分散，否决。

### D2 请求/响应契约

请求体（`POST /api/config/quick-assign`）：

```json
{
  "assignment": {
    "model": "deepseek-v4-pro",
    "provider": [
      { "provider": "volc-engine", "model": "deepseek-v4-pro" },
      { "provider": "bigmodel.cn" }
    ]
  },
  "targets": [
    { "scope": "user" },
    { "scope": "project", "project": "proj-a" }
  ],
  "source_scope": { "scope": "user" }
}
```

- `assignment.model` 可省略或空串（不写角色级缺省模型）；`assignment.provider` 必须是非空数组，每行 `provider` 非空字符串，`model` 可省略/空串（留空表示不指定元素级模型）。
- `targets` 非空数组；元素 `scope` 只能为 `user`（无 project 字段）或 `project`（`project` 非空字符串，必须是 dashboard 已注册项目）。前端负责把「本作用域」展开为具体 `targets` 元素并去重；服务端对重复目标按 `(scope, project)` 去重后只写一次。
- `source_scope` 指定 provider 定义来源作用域：`{"scope":"user"}` 取用户级 raw `llm.providers`；`{"scope":"project","project":"<name>"}` 取该项目 `read_effective_config` 的 `llm.providers`（即设置页当前作用域看到的那份有效列表，正是弹窗里可选 provider 的来源）。
- 请求级非法（body 非对象、assignment/targets/source_scope 非法、项目名未注册/不可解析）→ `400 {"error": "..."}` 且**不写任何目标**。
- 执行成功（含部分失败）→ `200 {"ok": bool, "results": [{ "scope": "user"|"project", "project": "<name>"?, "ok": bool, "error": "<失败原因>"?, "path": "<写入文件路径>" }]}`；`ok` 为全部目标成功。失败原因来自该目标 `_write_config_locked` 返回的 `error`，或 provider 无法补齐的明确提示（含缺失 provider 名）。

### D3 服务端解析 provider 定义来源，而不是客户端上传 `provider_defs`

`source_scope` 是唯一输入：用户级 → 读用户级 raw `llm.providers`；项目级 → `read_effective_config(project_path)` 的 `llm.providers`。理由：与设置页当前作用的 provider 下拉同源；定义（含 `apikey`）不出服务端；补齐目标与实际生效视图一致。备选「前端上送 provider_defs」被否（数据来源多一份、apikey 传输、需信任客户端）。

### D4 项目级写入：先校验再补齐，补齐与分配在同一目标写入内完成

数据层新增 `quick_assign_models(...)`（名称与签名以实现为准），对每个项目目标：

1. 持 `_CONFIG_WRITE_LOCK`，读目标项目 raw config（缺失视为 `{}`），取 `llm.providers` 列表（非列表按空列表处理并交给既有校验兜底）。
2. 计算模板候选链引用的 provider 名集合（去重）；`missing = referenced - 项目既有 provider 名集合`。
3. 若 `missing` 非空：从 D3 的源 provider 定义列表按 name 建立映射；`missing` 中任一在源中不存在 → 该目标直接返回失败（错误含缺失名），不写盘；否则构造项目级 patch 的 `llm.providers = 项目既有列表 + 缺失定义深拷贝`（同名保留项目既有定义，绝不覆盖）。
4. patch 的 `agents.models` = 对 `ConfigLoader.KNOWN_AGENT_TYPES` **全部角色**生成同一份 `{model?, provider:[...]}` 深拷贝，经 `serialize_models_patch` 得到规范形态。
5. 调 `_write_config_locked(project_root, patch, scope="project")`（本函数内已持锁，直接复用内部实现，天然复用既有校验与原子写；无缺失时 patch 不携带 `llm` 段）。返回 `{"ok","error","path"}` 转成逐项结果。
6. 用户级目标：patch 仅 `{"agents": {"models": ...}}`，调 `_write_config_locked(None, patch, scope="user")`。若用户级 raw 缺模板引用的 provider，则既有校验返回失败 → 该目标失败（与项目目标同口径，不做用户级自动补齐：用户级无「上级」可补）。

`_deep_merge_managed` 对 `llm` 段逐键替换、`providers` 列表整体替换，因此项目补齐 patch 只带 `providers` 时不会清掉项目 `llm` 段其他键；`agents.models` 整体替换符合「覆盖全部角色」需求。

### D5 角色全集与规范形态单源

角色列表一律取 `ConfigLoader.KNOWN_AGENT_TYPES`（当前 13 个），不另外硬编码后端角色表；前端只显示角色数量（`已加载的 Agent 角色数`，用于提示「覆盖全部角色」），不参与写入。写入形态经 `ConfigLoader.serialize_models_patch` 与单角色保存完全一致（单行无元素级模型 → 字符串；否则数组；角色级 model 非空才保留）。

### D6 前端：面板入口 + 独立弹窗 + 纯函数可测

- `AgentModelPanel` 新增 props：`projects?: string[]`（已注册项目名列表）、`onQuickAssignApplied?: (result: QuickAssignResponse) => void`；在 `<h3>模型分配</h3>` 标题行右侧放「快速分配」按钮（antd `Button`，small 档），点击打开弹窗；弹窗状态放组件内 `useState`。
- 新增 `QuickAssignModal.tsx`：`Modal`（`title="快速分配"`，footer 取消/应用），内容为：角色默认模型 `Input` + `Form.List` 候选链行（provider `Select` options 来自 `props.config.llm.providers` 的 name，model `Input`，删除行、新增行按钮；至少保留一行）；作用域区 `Checkbox`「本作用域（用户级 / 项目 X）」（默认勾选）+ `Checkbox`「指定项目」联动 `Select mode="multiple"`（options = `projects`）；顶部说明文案提示「将覆盖全部 N 个 Agent 角色的模型分配」。模板为空（无有效 provider 行）或无目标时应用按钮 disabled。
- 抽纯函数到 `src/utils/agentModels.ts`（便于 `node --test` 直接加载）：`buildQuickAssignAssignment(roleModel, rows)`（trim、丢空行、model 留空省略）、`buildQuickAssignTargets(includeCurrent, project, selectedProjects)`（去重、本作用域展开为 user/project 目标）。弹窗仅做表单与展示，payload 由纯函数构造。
- 应用流程：先构造 payload → 若 `includeCurrent` 且 `anyPanelDirty()` → `Modal.confirm` 提示「覆盖全部角色分配并丢弃未保存修改」，取消则中止 → `quickAssignConfig(payload)`（`saving` 防重入）→ 成功回调父级 `onQuickAssignApplied(result)`；失败/部分失败以 `Modal.error`（或成功+失败分列的结果弹层）逐项展示，不掩盖失败。
- 成功后 `index.tsx` 的 `handleQuickAssignApplied(result)`：若结果含「本作用域目标且 ok」（`scope==='user'` 或 `scope==='project' && project===当前项目`）→ 同步 `snapshotPanelDirty()` → `getConfig(project)` 重载 → 作用域币值守卫后 `setConfig`（复用 `handleSave` 重载尾段的同一口径；重载失败沿用既有 warning 文案）；若仅指定项目成功 → 不重载、仅提示成功（当前表单与编辑内容不变）。弹窗关闭。
- `services/dashboard.ts` 新增类型 `QuickAssignTarget` / `QuickAssignAssignment` / `QuickAssignResponse` 与 `quickAssignConfig(payload): Promise<QuickAssignResponse>`（POST `/api/config/quick-assign`，沿用 `request<T>`）。

### D7 UI 约束与移动端

弹窗静态渲染（无动效，符合 DESIGN.md 红线）；颜色/间距取 `theme.ts` 与既有设置页卡片规范（灰底卡 10px 圆角 + `#d7d7d7` 边框仅用于卡片容器，弹窗内部沿用 antd 默认）；`Modal` 保留默认可滚动 body，footer 按钮常驻可达；移动端不改变既有面板结构，弹窗宽度自适应（`width` 用响应式值或 `styles.body` 限高滚动），不引入横向溢出。空值展示「—」（如未选择项目时的占位）。

### D8 测试策略

- 纯函数（payload 构造、目标去重、空行过滤）：`core/dashboard/static/tests/agentModels.test.mjs` 用 `node --test` 直接加载 `.ts`。
- 弹窗控件形态（模板行、作用域选项、禁用条件、结果展示）：新建 `core/dashboard/static/tests/quickAssign.test.mjs`，沿用 `tests/hooksPanel.test.mjs` 的 esbuild 打包 + `react-dom/server` SSR 断言范式（react/antd external）。
- 数据层：`tests/test_dashboard_data.py` 覆盖用户级全角色覆盖、项目补齐、同名保留、无法补齐失败、部分成功、其他键保留。
- API 层：`tests/test_dashboard_api.py` 覆盖成功、项目补齐、部分失败仍 200、请求级非法 400、未知项目 400。

## Risks / Trade-offs

- [整体覆盖不可撤销，可能误覆盖全部角色] → 应用前确认弹窗 + 结果明确列出目标；配置为明文 YAML，可手工回滚；不做自动备份（避免引入新持久化面）。
- [apikey 被复制到多个项目级配置] → 属用户显式操作，且 provider 配置本就是本地明文；复制使用深拷贝，保留项目既有同名定义不覆盖。
- [逐目标写入非事务，可能部分成功] → 设计即接受部分成功并逐项回报（需求要求）；失败目标不落盘（每个目标内部原子写）。
- [项目 provider 列表整体替换语义下，补齐 patch 携带完整列表，可能与并发写竞争] → 持 `_CONFIG_WRITE_LOCK` 内读-改-写，窗口短；dashboard 写操作本就串行。
- [角色表演进（新增角色）导致旧前端提示数量不准] → 后端以 `KNOWN_AGENT_TYPES` 为唯一写入依据，前端数量仅提示；不硬编码后端角色表。
- [源作用域 provider 定义与目标项目实际可用网络/计费不一致] → 沿用既有 provider 语义，不额外校验连通性；健康检测仍由单角色/Provider 页签承担。
- [弹窗内 provider 下拉只显示当前作用域有效 providers，可能缺目标项目独有 provider] → 模板只能引用当前作用域已有的 provider，符合「从当前作用域补齐」语义；缺定义时该目标失败并提示。

## Migration Plan

- 纯增量部署：后端新增端点与数据层函数、前端新增按钮/弹窗；无配置格式变化、无数据迁移、无需 daemon 停机。
- 回滚：回退前端与后端代码即可（端点无后台副作用；已写入的配置保持有效形态，可继续用单角色编辑）。
- 生效口径：快速分配写入后沿用既有提示「配置已保存，重启 daemon 后生效」。

## Open Questions

- 无。弹窗是否需要记住上次模板属后续可选优化（非本 SPEC 范围）。
