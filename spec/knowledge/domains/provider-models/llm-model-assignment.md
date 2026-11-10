<!-- knowledge: capability=llm-model-assignment rev=2 sources=spec/archive/2026-09-02-add-fenix-config,spec/changes/add-agent-model-quick-assign -->

# 角色模型分配（llm.providers 注册表 + agents.models 路由）

按 agent 角色把 LLM 网关与模型分配下去：`llm.providers` 定义命名 provider 注册表，`agents.models` 把角色路由到 provider，运行时以环境变量与 `--model` 注入；设置页另提供「快速分配」把一份模板整体覆盖到全部角色。

## 规则

- provider 注册表位于 `.fenix/config.yaml` 的 `llm.providers`：每项含 `name`（唯一标识）、`baseurl`（Anthropic 兼容端点）、`apikey`（访问密钥）必填字段，可含 `model`（该 provider 默认模型名）与 `sdk_model`（用于通过 claude-code SDK 模型名校验的官方模型名）。未配置 `llm.providers` 视为空注册表，行为不变。
- ConfigLoader 校验 provider 结构：`providers` 须为列表、每项 `name`/`baseurl`/`apikey` 非空、`name` 唯一；校验失败抛出带字段说明的配置错误，拒绝加载。
- `agents.models.<role>` 为角色分配项：`provider` 引用 `llm.providers` 中已定义的名称（支持单值与候选链形态，见 [provider-chain-config](provider-chain-config.md)），`model` 为链内全链缺省模型名（非必填，元素级解析顺序见 [chain-model-mapping](chain-model-mapping.md)）。
- 分配生效时，该角色 claude 子进程注入 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`，并传入 `--model`（值为 `sdk_model` 或官方模型名），`sdk_model` 即实际发往 provider 网关的模型名。
- 未在 `agents.models` 中登记的角色视为未分配：运行时维持默认模型行为，不注入任何覆盖环境变量（回退默认网关）；链缺失时同样走默认网关兜底。
- Dashboard 经 `GET/POST /api/config` 可视化编辑受管键 `llm` 与 `agents.models`：POST 写入前执行与 ConfigLoader 一致的校验，失败返回 400 且不写盘；保存成功提示「配置已保存，重启 daemon 后生效」。
- `config.template.yaml` 含 `llm.providers`、`agents.models`、`gates.approve_mode` 的带注释骨架；旧版配置缺省这些字段时正常运行（能力不激活），不得强制迁移。

**快速分配（一份模板覆盖全部角色）**

- 设置页「Agent 模型分配」页签的「模型分配」标题区提供「快速分配」入口，弹窗内编辑分配模板：角色级缺省模型（可空）+ 至少一行 provider+模型候选链（行序即候选回退顺序），与单角色分配同语义。模板仅存于弹窗会话，不持久化预设、不提供撤销快照。
- 应用时 `ConfigLoader.KNOWN_AGENT_TYPES` 全部已知 Agent 角色（当前 13 个）的 `agents.models` 被整体覆盖为该模板：每个角色获得相同缺省模型与相同顺序候选链，原有分配被替换而非合并；写入形态经 `serialize_models_patch` 规范化，与单角色保存一致（单行且无元素级模型 → provider 名字符串形态）。模板无有效 provider 行或未选任何目标时禁止应用、不发出任何写入；`agents.subagent_model_override` 及其他 agents/llm 键不受影响。角色数量提示仅展示用，后端以 `KNOWN_AGENT_TYPES` 为唯一写入依据，不硬编码角色表。
- 作用域目标两类可勾选兼投：「本作用域」（设置页当前所选用户级/项目级配置）与「指定项目」（多选 dashboard 已注册项目，逐项目写其项目级配置，与当前页作用域无关）；同一目标按 `(scope, project)` 服务端去重只写一次。请求级非法（body/assignment/targets/source_scope 形态非法、项目未注册）一律 400 且不写任何目标。
- 项目级写入先补齐 provider：项目级写路径的 provider 引用校验只看项目 raw 配置、不含用户级继承，故模板引用而项目自身 `llm.providers` 缺失的定义，须从 `source_scope` 来源作用域按名称复制完整定义追加到该项目 `llm.providers`（项目既有定义保留、同名定义不被覆盖），补齐与分配在同一目标写入内完成。来源口径：`scope=user` 取用户级 raw `llm.providers`；`scope=project` 取该项目有效配置的 `llm.providers`（与弹窗 provider 下拉同源）。源作用域也不存在该定义时该目标失败（错误含缺失 provider 名）不落盘；用户级目标不做补齐（无上级可补），缺 provider 即失败。
- 逐目标写入、逐目标回报：`POST /api/config/quick-assign` 执行阶段（含部分失败）恒 200，返回 `{"ok", "results": [{scope, project?, ok, error?, path}]}`；单目标失败不阻止其他目标（部分成功语义），失败目标不落盘。多目标读-改-写全程持 `_CONFIG_WRITE_LOCK`，每目标独立原子写。
- 界面反馈与刷新：应用期间提交按钮 loading/disabled 防重复提交；面板存在未保存修改且目标含本作用域时先弹覆盖/丢弃确认，取消则不发起写入。全部成功提示成功目标数量，存在失败逐项展示失败目标与原因，不以单一成功提示掩盖失败。本作用域写入成功后配置页重载回填新分配并清除该面板判脏；仅写指定项目时不重载、不覆盖正在编辑的表单。写入成功沿用「配置已保存，重启 daemon 后生效」提示。
- 弹窗遵循界面设计宪法（DESIGN.md）：静态渲染无动画/过渡/装饰动效、颜色取自 `theme.ts` 单源、空值显示「—」；移动端弹窗可完整滚动、应用/取消可达、无横向溢出，不压缩或改变既有面板信息结构。

## 代码锚点

- 写入与 provider 补齐（多目标读-改-写、部分成功）：`core/dashboard/data/config_admin.py`（quick_assign_models / _source_provider_defs / _write_config_locked）
- 端点请求级校验与路由注册：`core/dashboard/routes/settings_routes.py`（_api_config_quick_assign）、`core/dashboard/routes/base.py`（POST /api/config/quick-assign）
- 前端入口与弹窗：`core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx`、`core/dashboard/static/src/pages/settings/components/QuickAssignModal.tsx`；payload 纯函数 `core/dashboard/static/src/utils/agentModels.ts`；API 封装 `core/dashboard/static/src/services/dashboard.ts`（quickAssignConfig）
- 守卫测试：`tests/test_dashboard_data.py`、`tests/test_dashboard_api.py`、`core/dashboard/static/tests/quickAssign.test.mjs`、`core/dashboard/static/tests/agentModels.test.mjs`

## 溯源

- 史前复原 — 迁移期已存在的基线：agent 按角色路由模型分配，sdk_model 即 --model 直接发往 provider 网关；未登记角色回退默认网关
- 2026-09-02 add-fenix-config（spec/archive/2026-09-02-add-fenix-config） — 固化 provider 注册表结构、角色分配与环境变量注入契约、Dashboard 配置页读写闭环与模板骨架
- 2026-11-10 add-agent-model-quick-assign（spec/changes/add-agent-model-quick-assign/） — 新增快速分配规则组：一份模板整体覆盖全部已知角色、本作用域/指定项目目标、项目级 provider 自动补齐（保留既有同名定义）、逐目标部分成功回报与本作用域成功后面板刷新
