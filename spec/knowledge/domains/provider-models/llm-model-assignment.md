<!-- knowledge: capability=llm-model-assignment rev=1 sources=spec/archive/2026-09-02-add-fenix-config -->

# 角色模型分配（llm.providers 注册表 + agents.models 路由）

按 agent 角色把 LLM 网关与模型分配下去：`llm.providers` 定义命名 provider 注册表，`agents.models` 把角色路由到 provider，运行时以环境变量与 `--model` 注入。

## 规则

- provider 注册表位于 `.fenix/config.yaml` 的 `llm.providers`：每项含 `name`（唯一标识）、`baseurl`（Anthropic 兼容端点）、`apikey`（访问密钥）必填字段，可含 `model`（该 provider 默认模型名）与 `sdk_model`（用于通过 claude-code SDK 模型名校验的官方模型名）。未配置 `llm.providers` 视为空注册表，行为不变。
- ConfigLoader 校验 provider 结构：`providers` 须为列表、每项 `name`/`baseurl`/`apikey` 非空、`name` 唯一；校验失败抛出带字段说明的配置错误，拒绝加载。
- `agents.models.<role>` 为角色分配项：`provider` 引用 `llm.providers` 中已定义的名称（支持单值与候选链形态，见 [provider-chain-config](provider-chain-config.md)），`model` 为链内全链缺省模型名（非必填，元素级解析顺序见 [chain-model-mapping](chain-model-mapping.md)）。
- 分配生效时，该角色 claude 子进程注入 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`，并传入 `--model`（值为 `sdk_model` 或官方模型名），`sdk_model` 即实际发往 provider 网关的模型名。
- 未在 `agents.models` 中登记的角色视为未分配：运行时维持默认模型行为，不注入任何覆盖环境变量（回退默认网关）；链缺失时同样走默认网关兜底。
- Dashboard 经 `GET/POST /api/config` 可视化编辑受管键 `llm` 与 `agents.models`：POST 写入前执行与 ConfigLoader 一致的校验，失败返回 400 且不写盘；保存成功提示「配置已保存，重启 daemon 后生效」。
- `config.template.yaml` 含 `llm.providers`、`agents.models`、`gates.approve_mode` 的带注释骨架；旧版配置缺省这些字段时正常运行（能力不激活），不得强制迁移。

## 溯源

- 史前复原 — 迁移期已存在的基线：agent 按角色路由模型分配，sdk_model 即 --model 直接发往 provider 网关；未登记角色回退默认网关
- [2026-09-02 add-fenix-config](spec/archive/2026-09-02-add-fenix-config/) — 固化 provider 注册表结构、角色分配与环境变量注入契约、Dashboard 配置页读写闭环与模板骨架
