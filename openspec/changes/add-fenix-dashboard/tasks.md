## 1. agent-run-artifacts（框架核心改造，先行）

- [x] 1.1 改造 `core/agent_runner.py::_run_claude`：由 `subprocess.run(capture_output=True)` 改为 `subprocess.Popen` + `--output-format stream-json`，用 stdout/stderr 双守护线程逐行读取，将每行 JSON 事件追加写入 `.fenix/runs/<run_id>.jsonl`（含非 JSON 行以 `{"type":"stderr","line":...}` 兜底），逐行 flush 保证运行期间可读
- [x] 1.2 解析流的最终 `result` 事件还原 `output` 与 `turns`，返回与现状等价；异常/超时/kill 时向产物文件追加 `{"type":"error",...}` 终态行并仍按现状抛 `RuntimeError`；确认现有调用方（`AgentRunResult`、verifier 读 `.fenix-run-result.json`、重试逻辑）不受影响
- [x] 1.3 `.fenix/runs/` 清理（仅保留最近 20 个、跳过正在增长的活动产物）+ 模板 gitignore 加入 `.fenix/runs/`
- [x] 1.4 兼容性测试：正常完成、超时/异常、stderr 兜底三种路径；运行 `python3 -m pytest tests/ -v` 全绿

## 2. dashboard-server（数据层 + HTTP 服务）

- [x] 2.1 新建 `core/dashboard/data.py`，把 `bin/fenix_dashboard.py` 已验证的 `parse_state`/`parse_tasks`/`count_scenarios`/`get_recent_events` 提取为共享函数并增强容错（progress 文件损坏/非对象时跳过不崩溃），TUI 与 Web 共用
- [x] 2.2 新建 `core/dashboard/registry.py`：读写 `~/.config/fenixd/dashboard.yaml`（port/projects/scan_dirs）、`discover()`（显式配置 + 目录扫描，识别条件为同时存在 `STATE.md` 与 `.fenix/config.yaml`）、`add_project()` 去重注册
- [x] 2.3 新建 `core/dashboard/server.py`：`ThreadingHTTPServer` 仅绑 127.0.0.1，实现 `GET /api/projects`、`/api/overview`、`/api/specs`、`/api/specs/<spec>`、`/api/runs/<run_id>`、`/api/events` 六端点（JSON、容错解析、数据源损坏以字段标记）；实现截图静态服务 `/screenshots/<project>/<spec>/<file>`（`resolve()`+`is_relative_to` 防穿越、仅限注册项目）
- [x] 2.4 改 `bin/fenix_dashboard.py` 为统一入口：`--serve`（默认，启动 Web 服务，端口冲突自动向上探测并打印实际 URL）/ `--tui`（保留原终端仪表盘）/ `--add-project <path>` / `--port N` / `--list-projects`

## 3. dashboard-ui（浏览器前端）

- [x] 3.1 前端骨架（`core/dashboard/static/`：index.html + app.js + style.css，原生 JS、无 CDN）：项目选择器 + 跨项目概览卡片（状态统计/任务进度条/问题数/活跃运行数），2 秒轮询 `/api/overview`
- [x] 3.2 SPEC 列表与详情视图：任务分组勾选、验证进度条、逐场景结果与断言、bug 列表（失败场景 + `verification-report.md` 尽力解析）、失败截图缩略图（点击放大）
- [x] 3.3 运行记录 + 实时 LLM 对话渲染：按 run_id 展示运行列表（运行中/已完成/异常终止），运行中记录自动轮询 `/api/runs/<run_id>` 渲染 assistant 文本、tool_use 名称与输入摘要、tool_result、error 终态
- [x] 3.4 刷新体验：自动刷新不丢滚动位置、接口失败/空数据兜底展示而非白屏

## 4. fenix-dashboard-skill + 安装 + 端到端

- [x] 4.1 新增 `skills/fenix-dashboard/SKILL.md`：探测服务（tmux session `fenix-dashboard`/端口）→ 未运行则 tmux 启动 `python3 <框架>/bin/fenix_dashboard.py --serve` → `--add-project .` 注册当前项目 → 输出 `http://localhost:<port>` 与项目列表摘要
- [x] 4.2 `install.sh` 自动接入新 skill（沿用 `skills/*/` 通配，确认软链目标）+ 安装完成提示提及 dashboard；`config.template.yaml` 增加可选 `dashboard.port` 配置
- [x] 4.3 端到端验证：真实启动 Dashboard 服务 → 逐一验证六端点返回 → 浏览器/无头请求验证 UI 渲染、截图可访问、运行中 Agent 对话可见 → 执行 `/fenix-dashboard` skill 流程冒烟
