<!-- knowledge: capability=provider-chain-config rev=1 sources=spec/archive/2026-09-02-add-provider-failover -->

# provider 候选链配置

`agents.models.<role>.provider` 的多候选链结构：角色可配置按序尝试的 provider 候选链，派发失败时沿链切换。

## 规则

- `agents.models.<role>.provider` 支持 `str` 与 `list` 两种形态：list 为按序候选链，首元素为首选；单值形态解析为单元素链，行为与无链配置完全一致。
- 链元素支持字符串与对象两种形态；对象元素可携带元素级 `model`，元素级解析顺序见 [chain-model-mapping](chain-model-mapping.md)。
- config loader 在启动与热更新时校验链中每个名字存在于 `llm.providers`：未知名字打 ERROR 日志但不阻塞加载，该元素在运行期被跳过。
- 切换到链上第 N 项时，注入的 `ANTHROPIC_BASE_URL` / `API_KEY` / `MODEL` 三件套全部来自第 N 项 provider 自身配置，`CLAUDE_CONFIG_DIR` 隔离目录同步切换；链条目仅引用 provider 名，模型按元素级解析（见 [chain-model-mapping](chain-model-mapping.md)）。
- Dashboard 链编辑器可对候选链排序保存；后端校验失败的非法链以 400 拒绝、配置不落盘（编辑器契约见 [dashboard-chain-editor](dashboard-chain-editor.md)）。

## 溯源

- 史前复原 — 迁移期已存在的基线：provider 候选链元素为对象形态并支持元素级模型解析；Dashboard 链编辑器可排序保存，非法链 400 拒绝
- [2026-09-02 add-provider-failover](spec/archive/2026-09-02-add-provider-failover/) — 固化 str/list 双形态链解析、未知名字告警不阻塞、切换后三件套与隔离目录按链元素整体切换的契约
