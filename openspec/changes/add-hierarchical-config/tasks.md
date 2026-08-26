# Tasks: add-hierarchical-config

## 1. ConfigLoader 核心：深度合并与有效配置解析

- [ ] 1.1 `core/config.py` 新增常量 `USER_CONFIG_DIR = Path.home() / ".fenix"`，并新增纯函数 `deep_merge(base, override) -> dict`：dict 递归合并（override 优先）、标量/list 整体替换、不修改入参
- [ ] 1.2 `core/config.py` 新增 `resolve_config(project_root) -> dict`：读用户级 `~/.fenix/config.yaml` 与项目级 `<project_root>/.fenix/config.yaml`（任一或全部缺失按空 dict 兜底，解析失败记录 error 不阻断），`deep_merge(user, proj)`，缺 `project.name` 时以 `Path(project_root).name` 补齐，校验后返回
- [ ] 1.3 `core/config.py` 放宽校验：`_validate` 增加 `require_project` 参数（默认 True），`resolve_config` 调用时传 False；仅当 `project` 存在时才校验 `project.type`；`REQUIRED_KEYS` 缺失不再抛错改为逐键存在性校验（缺省交由消费方默认值兜底）
- [ ] 1.4 `tests/test_core.py` 新增 `deep_merge` / `resolve_config` 单测：覆盖 D2 合并语义（个别键覆盖、列表替换、无用户级时不变）、缺失文件兜底、`project.name` 补齐、校验放宽
- [ ] 1.5 运行 `pytest tests/test_core.py -q`，新单测全部通过

## 2. Daemon 加载切换

- [ ] 2.1 `fenixd.py` 第 68-69 行改为 `self.config = ConfigLoader.resolve_config(PROJECT_ROOT)`，废弃 `FENIX_DIR / "config.yaml"` 直读路径
- [ ] 2.2 运行 `pytest tests/ -q` 回归（现有 daemon/agent/admin 测试不因加载路径变化而失败）

## 3. Dashboard data 层：作用域化读写

- [ ] 3.1 `core/dashboard/data.py` 新增 `USER_CONFIG_PATH = Path.home() / ".fenix" / "config.yaml"`，`read_config` 增加 `scope`（`user`/`project`）参数：`scope="user"` 读用户文件，`scope="project"` 读项目文件
- [ ] 3.2 `core/dashboard/data.py` 新增 `read_effective_config(project_root)`：对受管键（llm / agents.models / agents.max_concurrent / gates.approve_mode）返回有效合并值 + `sources` 标注（该键在项目级文件显式定义 → `project`，否则 `user`）+ `scope` + `raw_exists`（当前作用域文件是否存在）
- [ ] 3.3 `core/dashboard/data.py` `write_config` 增加 `scope` 参数：`scope="user"` 写 `~/.fenix/config.yaml`（自动建目录），`scope="project"` 维持现状写项目文件；返回中携带 `scope` 与写入路径
- [ ] 3.4 `tests/test_dashboard.py` 新增 data 层单测：用户级读写、项目级有效合并与 sources 标注、写回保留非受管键、用户文件缺失兜底

## 4. Dashboard server API 作用域化

- [ ] 4.1 `core/dashboard/server.py` `_api_config_get`：无 project 参数 → 返回用户级配置（`scope=user`，不再返回 `unknown project`）；带 project → 校验存在性后用 `read_effective_config` 返回合并视图 + sources
- [ ] 4.2 `core/dashboard/server.py` `_api_config_post`：无 project 参数 → 写用户级配置；带 project → 写项目级；响应携带 `scope` 与写入路径
- [ ] 4.3 `tests/test_dashboard.py` 新增 API 层单测：无 project GET/POST、带 project 合并视图与来源、无 project 不再报 `unknown project`

## 5. Dashboard 前端双作用域渲染

- [ ] 5.1 `static/app.js` `renderConfig` 适配 `scope` 与 `sources`：`scope=user` 标题「配置管理 · 用户级」、`raw_exists=false` 提示「用户级配置文件尚不存在，保存后创建」；`scope=project` 显示合并值，对 `sources[key]=user` 的键显示「继承自用户级」badge
- [ ] 5.2 `static/app.js` `saveConfig`：用户模式 `POST /api/config`（无 project），项目模式 `POST /api/config?project=<name>`；保存成功横幅提示实际写入路径（`~/.fenix/config.yaml` 或 `<project>/.fenix/config.yaml`）
- [ ] 5.3 启动 dashboard（`bin/fenix_dashboard.py --serve`），浏览器验证：无项目进配置页为用户模式、选项目显示合并值 + 继承 badge、两种作用域保存写对文件

## 6. Registry 发现放宽

- [ ] 6.1 `core/dashboard/registry.py` `discover()` 扫描判定从「`STATE.md` 且 `.fenix/config.yaml`」改为仅 `STATE.md`（确认 `add_project` 仅依赖 `STATE.md`，无需改动）
- [ ] 6.2 `tests/test_dashboard.py` 新增 registry 单测：仅含 `STATE.md` 的目录被发现、`add_project` 对无 config 目录成功

## 7. 全量回归与收尾

- [ ] 7.1 运行 `pytest tests/ -q` 全量通过
- [ ] 7.2 检查 `grep -rn "unknown project" core/dashboard/` 确认 `/api/config` 路径不再产生该错误（其他 API 保持现状）
- [ ] 7.3 更新 README / 相关文档：说明配置分级与继承语义（用户级 `~/.fenix/config.yaml`、项目级覆盖、受管键来源标注）
