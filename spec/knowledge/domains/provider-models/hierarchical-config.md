<!-- knowledge: capability=hierarchical-config rev=1 sources=spec/archive/2026-09-02-add-hierarchical-config -->

# 分级配置（用户级 + 项目级深度合并）

配置分用户级与项目级两层，深度合并出有效配置；daemon 与 Dashboard 读写同走有效配置口径。

## 规则

- 两层配置路径：用户级 `~/.fenix/config.yaml`，项目级 `<project_root>/.fenix/config.yaml`，文件同名、作用域由所在目录决定；用户级存跨项目通用设置，项目级覆盖项目差异。
- 深度合并语义：以用户级为基础、项目级为覆盖——字典逐层递归合并（项目级优先），标量与列表由项目级整体替换（不做元素级合并）；项目级未显式定义的键继承用户级。
- `resolve_config(project_root)` 为有效配置统一入口：读取两层配置（任一或全部缺失均允许，缺失按空 dict 兜底），深度合并后返回；有效配置缺 `project.name` 时以项目根目录名补齐；对已存在键执行既有值级校验，顶层必填键缺失不强制报错（由消费方以默认值兜底）。
- daemon 启动使用 `resolve_config(PROJECT_ROOT)` 加载有效配置；两层配置文件均缺失时仍正常启动运行。
- Dashboard `/api/config` 双作用域：无 `project` 参数读写用户级配置；带 `project` 参数写项目级、读返回有效合并视图，并附 `sources`（标注每个受管键 `llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode` 来自用户级还是项目级）、`scope`（user/project）与 `raw_exists`（当前作用域文件是否存在）。
- 前端配置页双模式渲染：未选项目为用户模式（标题标注「用户级」，保存写入用户级文件；文件不存在时提示保存后创建）；选项目为项目模式（显示有效合并值，来自用户级的受管键旁标注「继承自用户级」，保存写入项目级文件并提示路径）。
- Registry 扫描与项目注册仅以 `STATE.md` 存在为识别条件，不要求 `.fenix/config.yaml` 存在——配置完全继承用户级的项目同样可被监控与注册。

## 溯源

- 史前复原 — 迁移期已存在的基线：配置按全局与项目两级深度合并（resolve_config）出有效配置；可选字段不强制存在校验；daemon 与 Dashboard 读写同走有效配置口径
- [2026-09-02 add-hierarchical-config](spec/archive/2026-09-02-add-hierarchical-config/) — 固化两层路径与深度合并语义、resolve_config 兜底与 project.name 补齐、Dashboard 双作用域读写与继承标注、注册识别放宽为仅 STATE.md
