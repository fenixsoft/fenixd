## Context

- 每项目运行独立 fenixd daemon（`/root/fenixd`、`/root/fenix-desktop` 各自持有 STATE.md / config.yaml 与独立 tmux session），这是刻意的隔离设计，本次不改变。
- 已有共享跨项目 Dashboard（`bin/fenix_dashboard.py --serve`，tmux session `fenix-dashboard`），通过 `core/dashboard/registry.py` 的 `Registry` 读取 `~/.config/fenixd/dashboard.yaml` 发现项目：
  - `projects`（显式注册）与 `scan_dirs`（目录扫描）合并；仅当目录同时存在 `STATE.md` 与 `.fenix/config.yaml` 才识别为 Fenixd 项目。
  - 现状 `scan_dirs` 为空（`[]`），因此扫描不生效；注册表只有手动注册的 `fenixd` 与 `/tmp/test-project`，这正是「Dashboard 只能看到 fenixd」的根因。
- `bin/fenix_session.py` 已实现项目级唯一 tmux session 名派生（`fenixd-<目录名>-<路径哈希6位>`）与运行判定（`is_running`：唯一名 `tmux has-session` + 旧版固定 `fenixd` session 按 cwd 匹配兼容）。
- 前端概览（`app.js` 的 `renderOverview`/`projectCard`）已遍历展示所有 `projects`，多项目展示骨架已具备。

## Goals / Non-Goals

**Goals:**
- 让 Dashboard 以自动扫描为主发现所有 fenixd 项目（默认扫描用户主目录一级子目录），手动注册作为补充，使「打开 Dashboard 即可看到所有被监控项目的开发状态」。
- 为每个被监控项目提供 daemon 运行健康状态（`running`/`stopped`），在概览卡片上展示。
- 支持把已注册项目移出监控列表（`--remove-project`），清理残留项目。
- 保持现有 API 容错约定：任何检测异常不使请求失败。

**Non-Goals:**
- 不改变每项目独立 daemon 的隔离架构（不做单 daemon 聚合调度、不做 supervisor）。
- 不初始化 trendradar2 等未设置 `.fenix` 的项目。
- 不做跨项目的 SPEC 级聚合视图（如把所有项目 SPEC 合入一个列表）；本次只保证「多项目发现 + 健康展示」。
- 不引入新的外部依赖（沿用标准库 + tmux）。

## Decisions

### D1. 默认扫描目录：`scan_dirs` 为空时回退到 `~`（主目录）一级子目录

现状 `discover()` 遍历 `scan_dirs` 下每个一级子目录，用 `STATE.md` + `.fenix/config.yaml` 双文件判定。当配置未提供 `scan_dirs` 时，默认以 `~` 作为唯一扫描根，复用同一套判定逻辑。`/root` 下 `fenixd`、`fenix-desktop` 即可被自动发现。

- **备选**：默认扫描一组常见项目根（`~/dev`、`~/projects`、`~/workspace`…）——多数不存在或覆盖面不匹配实际布局，且列表需维护；`~` 一级扫描更通用。
- **权衡**：`~` 下目录多时每次发现遍历稍慢。缓解：服务器侧 `projects()` 已有 10s TTL 缓存；一级 `iterdir()` 开销可忽略（判定基于文件存在性）。

### D2. daemon 健康检测：把 session 判定逻辑抽到 `core/fenix_session.py` 供共享

现状逻辑在 `bin/fenix_session.py`（CLI）。为避免 data.py 反向依赖 bin、也避免重复实现，将纯函数（`resolve_root`/`session_name`/`is_running`）抽到新模块 `core/fenix_session.py`，`bin/fenix_session.py` 改为薄 CLI 包装（对外 CLI 接口 `name`/`running`/`path` 不变，兼容既有 skill/statusline 调用）。`data.py` 的 `daemon_health(project_root)` 直接调用 `is_running`。

- **备选**：在 data.py 内联复制 tmux 判定——避免动 bin，但逻辑重复，两处易漂移。
- **权衡**：抽取有回归风险，故要求 `bin/fenix_session.py` 行为等价且保留原 CLI 契约（场景：`running`/`name`/`path` 输出不变）。

### D3. 健康状态语义与容错

`daemon_health(project_root)` 返回 `"running"` 或 `"stopped"`：任一 `tmux` 判定（唯一 session 命中或旧版 `fenixd` session cwd 匹配）成功即 `running`；`tmux` 不可用、subprocess 异常或未命中一律 `stopped`（容错，不抛异常）。API 层 project 对象新增 `daemon` 字段。

- **权衡**：tmux 不可用时一律显示「未运行」可能误报；但 Dashboard 目标机器均有 tmux（daemon 本就跑在 tmux 里），且容错优先于精确。

### D4. 健康检测的轮询开销控制

Dashboard 每 2s 轮询 `/api/overview`，内部对每个项目调 `project_summary`；若每次检测都 spawn `tmux has-session`，N 项目 × 每 2s 会产生 N 次子进程调用。缓解：`data.py` 内维护带 TTL（默认 5s）的 `daemon_health` 结果 memo（key=项目根，value=(状态, 时间戳)），在 TTL 内复用；同时 `overview` 与 `/api/projects` 共享该 memo，避免同一次轮询内重复检测。

### D5. `--remove-project <path>`：从显式 `projects` 移除

`Registry.remove_project(path)`：解析规范化路径后，从 `projects` 中删除匹配项并 `save()`；未注册（或仅被扫描发现的 volatile 项目）时返回未变更提示，不报错。`bin/fenix_dashboard.py` 新增对应子命令。用于清理残留项目（如 `/tmp/test-project`）。被扫描发现的默认项目无法被「移除」（不在配置中，扫描天然恢复），符合「扫描为主」的定位。

## Risks / Trade-offs

- [默认扫描 `~` 可能误入用户不希望监控的目录] → 判定强制要求 `STATE.md` + `.fenix/config.yaml` 双文件，非 fenixd 项目不进入；用户仍可用显式 `scan_dirs` 覆盖默认。
- [抽取 `core/fenix_session.py` 导致 bin CLI 回归] → 保持 CLI 契约不变；单测覆盖 `name`/`running`/`path` 三命令；`fenix-setup`/statusline 调用路径不变量。
- [tmux 不可用误报 stopped] → 容错语义下可接受；文档说明该字段依赖 tmux。
- [健康检测 subprocess 开销] → D4 的 TTL memo + 服务器 10s 发现缓存兜底。

## Migration Plan

1. 新增 `core/fenix_session.py`（从 bin 平移逻辑），`bin/fenix_session.py` 改为调用它（行为等价）。
2. `registry.py`：默认扫描 + `remove_project`。
3. `data.py`：`daemon_health` + memo；`project_summary`/`overview` 增加 `daemon` 字段。
4. `server.py` 无需改动（`/api/projects`/`/api/overview` 已基于 `project_summary`/`overview` 透传新字段）。
5. `bin/fenix_dashboard.py`：`--remove-project`。
6. 前端 `app.js`/`style.css`：概览卡片 daemon 徽标。
7. 单测（`tests/test_core.py`）：默认扫描、双文件判定、`remove_project` 去重/未注册提示、`daemon_health` 语义（用 mock 的 tmux 子进程）。
8. 人工验证：重启 `fenix-dashboard` 服务后，概览应自动出现 `fenix-desktop`（运行中）与 `fenixd`；用 `--remove-project /tmp/test-project` 清理残留。
9. 回滚：改动集中于 dashboard 聚合层与独立 CLI 脚本，`bin/fenix_session.py` 保持 CLI 契约，回滚 = 还原这几个文件。

## Open Questions

- 无阻塞性问题。`~` 默认扫描的行为是否要额外提供 `scan_dirs: [~]` 显式写法以显式化默认——实现时在 `registry.py` 文档字符串中说明即可。
