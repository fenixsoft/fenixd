# Design: 配置分级（用户级 + 项目级深度合并与继承）

## Context

fenixd 现状：
- `core/config.py::ConfigLoader` 负责 `.fenix/config.yaml` 的加载与校验；`REQUIRED_KEYS = ["project", "schedule", "agents", "worktree", "gates", "commands", "logging"]`，缺任一即抛 `ValueError`；`project.type` 必须在 `web|cli|library|api` 中。
- `fenixd.py`（第 68-69 行）启动时 `ConfigLoader.load(FENIX_DIR / "config.yaml")`，文件缺失抛 `FileNotFoundError`。
- Dashboard `core/dashboard/data.py`：`read_config(project_root)` / `write_config(project_root, patch)` 只读/写项目 `.fenix/config.yaml`，受管键白名单 `llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode`；写回用 `_deep_merge_managed` 只动受管键、保留其他键，原子写。
- Dashboard server `core/dashboard/server.py`：`_api_config_get` / `_api_config_post` 用 `_project_from_query` 解析项目，无项目即返回 `unknown project`（`_api_config_get` 第 349-350 行、`_api_config_post` 第 495 行）。
- 前端 `static/app.js`：`config` 路由 = `config/<project>` 或 `config`（无项目 → `project: ''`）；`fetchFor` 对 config 视图请求 `/api/config?project=`（空 project）→ 触发后端 `unknown project`。配置页渲染 `renderConfig`、保存 `saveConfig` 均只面向「某项目」。
- Registry `core/dashboard/registry.py`：`discover()` 扫描目录仅当同时存在 `STATE.md` 与 `.fenix/config.yaml`；`add_project` 要求 `STATE.md`。

用户诉求：① 配置分级，用户级放用户目录、项目级放项目目录，文件名统一 `.fenix/config.yaml`；② 项目级只覆盖用户级的个别键，未覆盖的继承用户级（非全文件覆盖）；③ 配置菜单不选项目时默认维护用户级配置。

已确认决策：
- D1 用户级路径：`~/.fenix/config.yaml`。
- D2 项目配置页显示：有效合并视图（用户级 + 项目覆盖），标注每个值来源层级（继承 badge）；保存写入当前作用域文件。
- D3 Registry 发现放宽：目录仅需 `STATE.md` 即识别。

## Goals / Non-Goals

**Goals:**
- 引入用户级配置 `~/.fenix/config.yaml`，与项目级 `.fenix/config.yaml` 深度合并，项目级优先。
- `resolve_config(project_root)` 返回有效配置；用户级/项目级任一或全部缺失都允许，内置默认兜底。
- Dashboard 配置页支持两种作用域：无项目 = 用户级，有项目 = 有效合并视图 + 来源标注；保存写入当前作用域。
- 消除 `/api/config` 无项目时的 `unknown project` 错误。
- Registry 扫描与注册放宽为仅需 `STATE.md`。
- 完全向后兼容：无用户级配置时合并结果 = 项目配置，现有项目行为不变。

**Non-Goals:**
- 不做配置热加载（维持现状：重启 daemon 生效）。
- 不扩展 Dashboard 配置页受管键集合（仍为 `llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode`）。
- 不做元素级列表合并（`llm.providers` 整体替换）。
- 不引入外部依赖（沿用标准库 + pyyaml）。
- 不改造 `/fenix-approve`、`fenix-init` 的既有行为（项目级配置生成流程不变；用户级配置由用户手工或 Dashboard 创建）。

## Decisions

### D1: 配置层级与路径

- 用户级：`~/.fenix/config.yaml`（`Path.home() / ".fenix" / "config.yaml"`）。
- 项目级：`<project_root>/.fenix/config.yaml`（现状不变）。
- 两文件同名 `.fenix/config.yaml`，作用域由所在目录决定。
- 替代方案：`~/.config/fenixd/config.yaml` —— 被用户否决（要求文件名统一）。

### D2: 深度合并语义

`core/config.py` 新增纯函数 `deep_merge(base: dict, override: dict) -> dict`：

- 对每个键递归：两值均为 dict → 递归合并；否则（标量 / list / None）→ override 覆盖 base。
- 不改入参，返回新 dict（`copy.deepcopy` 基座）。
- 语义：项目级覆盖用户级的某一两个键，其余键保持用户级值；`llm.providers` 等 list 整体替换。

### D3: 有效配置解析 `resolve_config(project_root)`

流程：
1. 读用户级文件 → `user`（缺失/解析失败按空 dict，解析失败记录错误日志，不阻断）。
2. 读项目级文件 → `proj`（缺失按空 dict）。
3. `effective = deep_merge(user, proj)`。
4. 补全 `project` 身份：若 `effective` 缺 `project`（或缺 `project.name`），用 `Path(project_root).name` 补齐 `project.name`；`project.type` 缺失时不参与校验（不做硬性默认，避免对既有项目产生语义偏差）。
5. 校验：校验逻辑从「全量 `REQUIRED_KEYS` 必填」放宽为「已有键全部校验 + 缺省键用默认兜底」。具体——保留 `_validate` 对已存在键的所有值级校验；将顶层 `REQUIRED_KEYS` 存在性检查改为「解析层不强制缺失键报错」，各消费方仍走 `config.get(key, default)` 兜底。
   - 实现建议：`ConfigLoader._validate` 增加 `require_project=False` 参数或拆分 `_validate_optional`，使解析出的有效配置在校验时跳过 project 必填（因为已由步骤 4 补齐或由消费方兜底）。
6. 返回 `effective`。

**既有 `load()` 保持**：直接读单文件 + 严格校验，供 Dashboard 写回前对项目级文件做局部校验时复用（`write_config` 内部现用 `_validate_llm` / `_validate_agent_models` 等子校验，不依赖顶层必填，不受影响）。

### D4: Daemon 加载

`fenixd.py::initialize` 第 68-69 行改为：
```python
self.config = ConfigLoader.resolve_config(PROJECT_ROOT)
```
- 用户级/项目级任一缺失都允许；两者都缺失时 `resolve_config` 返回「空 dict + project 补齐 + 默认兜底」的最小有效配置，daemon 正常启动。
- `FENIX_DIR / "config.yaml"` 的直读路径废弃。

### D5: Dashboard `/api/config` API

`core/dashboard/data.py` 新增作用域支持：

- 新常量 `USER_CONFIG_PATH = Path.home() / ".fenix" / "config.yaml"`。
- `read_config(scope_root, scope: "user"|"project") -> dict`：读取**指定作用域文件**的受管键；返回结构扩展：
  ```json
  {
    "llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
    "gates": {"approve_mode": "manual"},
    "scope": "user"|"project",
    "raw_exists": bool,          // 当前作用域文件是否存在
    "sources": {                 // 每个受管键的来源层级
      "llm": "user"|"project",
      "agents.models": "user"|"project",
      "agents.max_concurrent": "user"|"project",
      "gates.approve_mode": "user"|"project"
    },
    "error": str|null
  }
  ```
- 项目模式（`scope="project"`）的**显示值**：受管键取自 `resolve_config(project_root)`（有效合并值）；`sources` 由「该键在项目级文件中是否显式定义」判定（显式 → `project`，否则 `user`）。若用户级也缺省 → `user` 表示「继承自用户级缺省值」，前端按缺省处理。
- 用户模式（`scope="user"`）：显示值 + `sources` 全部为 `user`，读取 `~/.fenix/config.yaml`。

server 层：
- `_api_config_get(query)`：`project` 缺省 → `read_config(user, "user")`；带 project → `_project_from_query` 校验存在性，再 `read_config(proot, "project")`，`config["project"] = project["name"]`。不再返回 `unknown project`。
- `_api_config_post(query)`：无 project → 写 `~/.fenix/config.yaml`；带 project → 写项目级（现状逻辑）。写回仍复用 `write_config`（局部校验 + 原子写 + 保留非受管键）。返回新增 `scope` / 写入路径，便于前端提示。

### D6: Dashboard 前端配置页

`static/app.js`：

- 路由：`config`（无项目）→ 用户模式；`config/<project>` → 项目模式（现状）。
- 用户模式渲染：标题「配置管理 · 用户级」，副标题说明「写入 `~/.fenix/config.yaml`，其他项目继承」；`raw_exists=false` 时提示「⚠ 用户级配置文件尚不存在，保存后创建」。
- 项目模式渲染：显示合并后的有效值；对 `sources[key] === "user"` 的受管键显示「继承自用户级」badge；标题「配置管理 · <项目>」。
- 保存：用户模式 `POST /api/config`（无 project）；项目模式 `POST /api/config?project=<name>`（现状）。保存成功横幅提示写入路径（如 `已写入 ~/.fenix/config.yaml` / `已写入 <project>/.fenix/config.yaml`）。
- `fetchFor` / `renderConfig` / `hydrateConfigPage` / `saveConfig` 适配 `scope` 与 `sources`。

### D7: Registry 发现放宽

`core/dashboard/registry.py`：
- `discover()`：扫描判定从 `STATE.md 且 .fenix/config.yaml` 改为**仅 `STATE.md`**。
- `add_project()`：仅要求 `STATE.md`（移除对 `.fenix/config.yaml` 的隐式依赖——现实现只查 `STATE.md`，维持不变即可，确认无 config 检查）。
- 结果：配置完全继承用户级的项目也能被监控。

### D8: 向后兼容与迁移

- 无用户级配置：`deep_merge({}, proj) = proj`，与现状行为一致。
- 既有项目完整 `config.yaml`：项目级键全量覆盖（若有用户配置），或整体即有效配置（无用户配置），行为不变。
- 无需数据迁移；新文件为可选项，由用户手工或 Dashboard 首次保存创建。

## Risks / Trade-offs

- [合并语义被误解] 用户可能期望 list 也做元素级合并 → 设计明确 list 整体替换，并在 design/proposal 中写明；`sources` 标注让覆盖关系可见。
- [项目身份缺失] 纯继承用户级的项目无 `project.name` → 用项目根目录名补齐，报告/标题仍可读。
- [宽松校验掩盖错误] `resolve_config` 对解析失败按空 dict 兜底可能吞掉 YAML 语法错误 → 解析失败记录 error 返回（用户模式展示给前端；daemon 记日志），不静默丢弃。
- [Registry 误识别] 放宽为仅 `STATE.md` 可能把非 fenixd 目录识别为项目（若其含 `STATE.md`）→ 接受此权衡（用户已确认），`discovered` 标记保留，显式注册仍可精确控制。
- [用户级配置共享敏感信息] `~/.fenix/config.yaml` 含 apikey 等敏感字段 → 文档注明权限建议（仅当前用户可读），与项目级 gitignore 语义一致（用户目录天然不入库）。

## Migration Plan

1. 实现 `deep_merge` + `resolve_config`（含校验放宽），单测先行。
2. `fenixd.py` 切换到 `resolve_config`；回归现有 daemon 启动（无用户配置 → 行为不变）。
3. Dashboard data/server 作用域化 + 前端双模式；手工验证：无项目进配置页（用户模式）、项目配置页继承 badge、保存写对作用域。
4. Registry 放宽；`add_project`/扫描回归。
5. 全量 `pytest` 回归。

回滚：`resolve_config` 可整体回退为 `ConfigLoader.load(FENIX_DIR / "config.yaml")` 一行，无数据迁移残留。

## Open Questions

- 用户级配置中是否允许出现 `project` 键：设计上忽略（用户级不应定义项目身份），`resolve_config` 合并时项目级 `project` 键优先；若用户级写了 `project` 且项目级未写，用项目根目录名覆盖。无需用户确认，属实现细节。
