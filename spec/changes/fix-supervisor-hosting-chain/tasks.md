## Deliverables

```yaml
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/fenix_session.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/overview/components/ProjectCards.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/hook_engine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: skills/fenix-setup/SKILL.md
  kind: modify
- path: README.md
  kind: modify
- path: docs/help/04-cli.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
- path: docs/help/07-safeguards.md
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/11-faq.md
  kind: modify
- path: tests/test_supervisor_hosting.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. supervisor 项目根解析与启动守卫

- [x] 1.1 `bin/fenixd_supervisor.py`：`PROJECT_ROOT` 改为按 `--project-root` 参数 > `FENIX_PROJECT_ROOT` 环境变量 > `Path.cwd()` 三级解析（`expanduser().resolve()` 规范化），删除 `Path(__file__).resolve().parent.parent` 派生路径；`argparse` 只接受该一个可选参数，未知参数不改变既有启动方式。
- [x] 1.2 `bin/fenixd_supervisor.py`：新增启动守卫——解析出的项目根下必须存在 `.fenix/`（目录或软链），缺失时向 stderr 打印含解析来源（参数/环境变量/cwd）与解析结果的可读错误，以非零码 `sys.exit`，且必须在 `_write_supervisor_runtime()` 与 `start_daemon()` 之前返回。
- [x] 1.3 `bin/fenixd_supervisor.py`：`_write_supervisor_runtime()` 的写入内容在既有 `sigkill_wait`、`started_at` 之外追加 `pid`（`os.getpid()`）、`script_hash`（`bin/fenixd_supervisor.py` 内容 sha256，读取失败时省略该键而不中断）、`project_root`（解析出的绝对路径）；保持临时文件 + `os.replace` 的原子写与「失败不中断主流程」语义。
- [x] 1.4 `tests/test_supervisor_hosting.py`：覆盖 D1 三个事故场景——显式 `--project-root` 优先于 cwd；在含 `.fenix/bin` 软链的子项目 cwd 下启动时项目根解析为该子项目且不触碰主树路径；`.`fenix` 缺失时非零退出且不产生进程；另覆盖自报五字段完备与原子性。

## 2. 托管态判定

- [x] 2.1 `core/fenix_session.py`：新增 `supervisor_running(root) -> bool`——扫描 `/proc`，命中条件为 cmdline 含 `fenixd_supervisor` 且（该进程 cwd 解析后等于 `root`，或其 cmdline 的 `--project-root` 值解析后等于 `root`）；`/proc` 不可读或任何 `OSError`/`ValueError` 时返回 `False` 且不抛异常。判定逻辑与 `_daemon_procs_under` 并列复用，不得复制粘贴出第二套 cwd 解析。
- [x] 2.2 `core/fenix_session.py`：新增 `hosting_state(root) -> str`，返回 `"managed"`（`supervisor_running` 为真）/ `"unmanaged"`（`is_running` 为真但无 supervisor）/ `"stopped"`（两者皆无）；模块 docstring 同步更新为「daemon 托管态与唯一 tmux session 名」，不再只描述 tmux。
- [x] 2.3 `tests/test_supervisor_hosting.py`：覆盖三态判定（managed / unmanaged 事故回归 / stopped），并覆盖 `/proc` 不可用时 `supervisor_running` 返回 `False` 而不抛异常。

## 3. 唯一托管启停路径

- [x] 3.1 `core/fenix_session.py:start_daemon()`：session 命令改为 `cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`，不再直接执行 `.fenix/fenixd.py`；保留 `.fenix` 与 `.fenix/STATE.md` 前置校验、`already` 幂等与启动后轮询 `is_running` 的逻辑。
- [x] 3.2 `core/fenix_session.py:stop_daemon()`：改为按序执行「写 `.fenix/stop` → 经 `/proc` 定位并 SIGTERM 该项目 daemon 进程 → 轮询等待 daemon 与 supervisor 双双退出（上限 30 秒）→ 超时 `tmux kill-session` 并对残留 daemon/supervisor 补 SIGKILL → `finally` 清除 `.fenix/stop`」；`is_running` 为假时直接返回 `{"ok": True, "was_running": False}` 且不写 stop 文件。SIGTERM/SIGKILL 只允许作用于 cwd 或 `--project-root` 等于该项目根的进程，禁止按 cmdline 裸匹配杀进程。
- [x] 3.3 `core/fenix_session.py:start_daemon()`：启动前清理陈旧 `.fenix/stop`——仅当 `is_running(root)` 为假且 `supervisor_running(root)` 为假时删除，避免误删一次正在进行的停止操作留下的标记。
- [x] 3.4 `tests/test_supervisor_hosting.py`：覆盖启动后 daemon 的 ppid 等于该项目 supervisor pid、`hosting_state` 为 `managed`；重复启动返回 `already=True` 且不产生第二个进程；停止后 daemon 与 supervisor 双双不存在且 `.fenix/stop` 已清除；超时路径走 kill-session 且无孤儿残留。

## 4. 检测、告警与建议

- [x] 4.1 `fenixd.py`：把 `_check_supervisor_drain_consistency` 拆为「supervisor 存在性」与「drain 一致性」两项独立判定；存在性判定必须无条件执行（`admin.shutdown_drain_seconds <= 0` 时也必须检测），`drain <= 0` 只跳过一致性比对，保留既有两条 WARNING 文案不变。
- [x] 4.2 `fenixd.py`：存在性判定失败时，除既有 WARNING 外必须经 AdminStore 写入一条 `signal_type: supervisor_missing`、`severity: major` 的 escalation 告警，描述须含「未受 supervisor 托管，restart_request 不会被消费」，`recommended_action` 须指引经 Dashboard 项目页「安装托管」或 `/fenix-setup` 恢复托管；同类型未处置告警必须去重不重复追加。
- [x] 4.3 `core/hook_engine.py:_action_restart_daemon()`：写 `.fenix/restart_request` 之前调用 `supervisor_running(project_root)`；为假时返回失败（走既有 `_alert_failure` 链），detail 须含「本项目无 supervisor，重启请求不会被消费」；为真时维持现行写入与成功 detail。
- [x] 4.4 `core/admin_monitor.py:_detect_restart_failure()`：`recommended_action` 按 `hosting_state` 分支生成——`unmanaged`/`stopped` 时指引经 Dashboard「安装托管」或 `/fenix-setup`，`managed` 时指引检查 supervisor 进程与 daemon 排水状态；两种分支的文案都必须不含「`.fenix/bin/fenixd_supervisor.py`」这一直接启动命令。
- [x] 4.5 `tests/test_supervisor_hosting.py`：覆盖 `drain=0` 且无 supervisor 的项目 daemon 启动后仍产生 `supervisor_missing` 告警（事故回归）；`drain>0` 且有 supervisor 时静默无告警；重复启动不产生第二条未处置告警；`restart-daemon` hook 在无 supervisor 时报 failure 且失败 detail 不含「supervisor 将执行优雅重启」；`restart_failed` 建议文案在 `unmanaged` 时不含直接启动命令。

## 5. Dashboard 暴露与管理操作

- [x] 5.1 `core/dashboard/data.py`：`daemon_health` 保持复用 `core.fenix_session.is_running`；新增 `hosting_state` 的 TTL 缓存包装并在 `project_summary()` / `overview()` 的项目对象中填充 `hosting` 字段（`managed`/`unmanaged`/`stopped`），检测异常时与 `daemon` 一致以 `"stopped"` 兜底、不使请求 500。
- [x] 5.2 `core/dashboard/server.py`：`_api_project_lifecycle` 的 `restart` 分支在校验项目存在后、写 `restart_request` 前检查 `hosting_state`，为 `unmanaged` 时返回 `{"ok": False, "error": <含「未受 supervisor 托管」>}`；新增 `install-hosting` 动作——对 `managed` 幂等返回已托管、其余情况复用 `stop_daemon` + `start_daemon` 转入托管，成功后沿用既有 SSE `refresh` 广播；`_resolve_project_or_400` 的动作后缀剥离列表加入 `/install-hosting`。
- [x] 5.3 `core/dashboard/static/src/services/dashboard.ts` 新增 `installHosting(name)`；`core/dashboard/static/src/pages/overview/components/ProjectCards.tsx` 的 `DaemonBadge` 扩展为托管态三态显示（`unmanaged` 渲染为「运行中·未托管」警示样式），项目操作菜单在 `hosting === 'unmanaged'` 时新增「安装托管」项并按 `runAction` 同一路径调用与刷新，不改变既有启动/停止/删除项行为。
- [x] 5.4 `tests/test_supervisor_hosting.py`：覆盖 `/api/projects` 与 `/api/overview` 返回三态的 `daemon`/`hosting` 组合；`install-hosting` 对 `unmanaged` 成功转 `managed`、对 `managed` 幂等、对未监控项目返回 400；`restart` 对 `unmanaged` 返回可读错误且不视作成功。
- [x] 5.5 `core/dashboard/data.py:request_spec_approve_push()`：把消费方判据从 `_is_running(proot)` 升级为 `hosting_state(proot)`——`unmanaged` 时返回 `{"ok": False, "found": True, "unmanaged": True, "conflict": False, "daemon_down": False, "file": None, "created": None, "error": <含「未受 supervisor 托管」与经 Dashboard「安装托管」或 `/fenix-setup` 恢复托管的指引>}` 且 MUST NOT 写入信号文件；`stopped` 时维持既有 `daemon_down` 分支与「daemon 未运行，请先启动 daemon」文案逐字不变；`managed` 走既有校验与写入路径。`core/dashboard/server.py:_api_spec_approve_push()` 新增 `result.get("unmanaged")` → 409 分支（先于 `conflict` 判定，便于用户区分「托管链断了」与「已有请求在途」）。
- [x] 5.6 `tests/test_supervisor_hosting.py`：覆盖 `unmanaged` 项目审批推送返回 409 且 `.fenix/approve_push_request.json` 未被创建（事故回归）；`managed` 项目审批推送写入信号并返回成功；`stopped` 项目返回的文案与既有 `daemon_down` 文案逐字一致。

## 6. 技能与文档对齐

- [x] 6.1 `skills/fenix-setup/SKILL.md`：第 7 步「启动 fenixd」的 tmux 命令改为 `tmux new-session -d -s "${SESSION_NAME}" "cd $(pwd) && python3 .fenix/bin/fenixd_supervisor.py --project-root $(pwd) >> .fenix/logs/supervisor.log 2>&1"`，展示信息段的查看日志/停止说明同步改为指向 supervisor.log 与托管语义。
- [x] 6.2 `docs/help/04-cli.md`、`docs/help/06-governance.md`、`docs/help/07-safeguards.md`：补齐「唯一托管启动路径」的事实描述（tmux 只承担脱离终端）、托管态三态（managed/unmanaged/stopped）与「安装托管」恢复路径。
- [x] 6.3 `docs/help/08-dashboard.md`、`docs/help/09-config.md`：补 `hosting` 字段与「安装托管」操作说明；`09-config.md` 的 `supervisor_runtime.json` 相关段落补 `pid`/`script_hash`/`project_root` 三个新键及其用途（含 `script_hash` 不一致＝supervisor 持旧代码）。
- [x] 6.4 `docs/help/11-faq.md` 与 `README.md`：把「daemon 由 supervisor 托管」的表述与落地事实对齐，并新增一条 FAQ——「项目在跑但 restart_request 永不生效／概览显示未托管」的成因与「安装托管」处置步骤。

## 7. 回归验证

- [x] 7.1 运行 `python3 -m pytest tests/ -q` 全量通过，且 `tests/test_supervisor_hosting.py` 全绿。
- [x] 7.2 在 `core/dashboard/static` 执行 `npm install --no-audit --no-fund` 与 `npm run build` 成功，概览页可正常加载并显示托管态徽标（构建产物 `core/dashboard/static/dist/` 为 gitignored 运行时产物，不入库）。

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/fix-supervisor-hosting-chain/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
