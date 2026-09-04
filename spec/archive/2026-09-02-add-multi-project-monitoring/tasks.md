# Tasks: add-multi-project-monitoring

## 1. 共享 session 判定模块

- [x] 1.1 新建 `core/fenix_session.py`，从 `bin/fenix_session.py` 平移纯函数：`resolve_root` / `session_name` / `_legacy_session_matches` / `is_running`（含旧版固定 `fenixd` session cwd 匹配）
- [x] 1.2 将 `bin/fenix_session.py` 改为薄 CLI 包装，委托给 `core/fenix_session.py`，对外 CLI 契约（`name` / `running` / `path` 输出）保持不变

## 2. 自动发现与注册管理（registry.py / CLI）

- [x] 2.1 `Registry.discover()`：`scan_dirs` 未配置或为空时，默认以用户主目录 `~` 为唯一扫描根遍历一级子目录；仍以 `STATE.md` + `.fenix/config.yaml` 双文件判定；与显式 `projects` 按规范化路径去重
- [x] 2.2 实现 `Registry.remove_project(path)`：按规范化路径从配置 `projects` 移除并写回；未注册时返回未变更提示不报错
- [x] 2.3 `bin/fenix_dashboard.py` 新增 `--remove-project <path>` 子命令，调用 `Registry.remove_project`

## 3. daemon 健康检测与 API 透传（data.py）

- [x] 3.1 实现 `daemon_health(project_root)`：复用 `core.fenix_session.is_running`，返回 `"running"`/`"stopped"`；tmux 不可用/异常/未命中一律 `stopped` 不抛异常；带短 TTL（约 5s）memo 缓存避免重复 spawn
- [x] 3.2 `project_summary()` 与 `overview()` 的项目对象增加 `daemon` 字段（基于 `daemon_health`），经 `/api/projects` 与 `/api/overview` 透传；检测异常兜底 `"stopped"` 不 500

## 4. 前端概览展示（app.js / style.css）

- [x] 4.1 `app.js` 的 `projectCard` 增加 daemon 徽标：`"running"` → 「运行中」（正向色），`"stopped"` → 「未运行」（弱化/警示色）；保留「自动」标记
- [x] 4.2 `style.css` 增加 daemon 徽标样式（可复用现有 status-pill 类）

## 5. 单元测试（tests/test_core.py）

- [x] 5.1 测试默认扫描发现（`scan_dirs` 为空 → 扫描 `~`）、非 fenixd 目录排除、显式注册与扫描去重
- [x] 5.2 测试 `Registry.remove_project`：已注册移除成功、未注册不报错、仅扫描发现项目不可移除
- [x] 5.3 测试 `daemon_health` 语义（mock tmux subprocess）：唯一 session 命中 → running、旧版 session cwd 匹配 → running、未命中/异常 → stopped
- [x] 5.4 测试 `overview()`/`project_summary()` 含 `daemon` 字段且异常不抛（不 500）

## 6. 验证与收尾

- [x] 6.1 运行 `python3 -m pytest tests/ -v` 全部通过，无回归
- [x] 6.2 重启 `fenix-dashboard` 服务，浏览器确认概览自动出现 `fenixd`（运行中）与 `fenix-desktop`（运行中）且 daemon 徽标正确
- [x] 6.3 执行 `python3 bin/fenix_dashboard.py --remove-project /tmp/test-project` 清理残留项目，确认从监控列表移除
