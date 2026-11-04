## Deliverables

```yaml
- path: core/systemd_hosting.py
  kind: new
- path: core/fenix_session.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/hook_engine.py
  kind: modify
- path: bin/migrate_to_systemd.py
  kind: new
- path: skills/fenix-setup/SKILL.md
  kind: modify
- path: skills/fenix-dashboard/SKILL.md
  kind: modify
- path: tests/test_systemd_hosting.py
  kind: new
- path: tests/test_supervisor_hosting.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
- path: tests/test_hook_engine.py
  kind: modify
- path: tests/test_dashboard_orphan_guard.py
  kind: modify
```

## 1. systemd_hosting 模块与 unit 安装

- [ ] 1.1 新建 `core/systemd_hosting.py`：unit 模板生成（`fenixd-<项目名>.service` 项目名文件名安全化、WorkingDirectory/ExecStart=supervisor --project-root、`Restart=on-failure`、`SuccessExitStatus=75`、`TimeoutStopSec=2100`、`KillMode=mixed`、`RestartSec` 与 `StartLimitIntervalSec`/`StartLimitBurst`、`WantedBy=multi-user.target`）与 `fenix-dashboard.service` 模板（ExecStart=--serve + `Environment=FENIX_DASHBOARD_DETACH=1`）；幂等安装语义（unit 已存在且服务活跃不重建不重启）与 systemctl 不可用可读错误路径
- [ ] 1.2 env 捕获函数：读 `/proc/<pid>/environ` → 会话身份 denylist 前缀族过滤（CLAUDE_PID/CLAUDECODE/CLAUDE_CODE_*/AI_AGENT/IS_SANDBOX/GIT_ASKPASS）→ 生成 0600 EnvironmentFile 候选稿；键集来源为在跑进程实环境而非白名单

## 2. supervisor 退出码协议

- [ ] 2.1 `bin/fenixd_supervisor.py` 四条有意退出路径落实退出码：停机信号收尾与 stop 旗标在场退出 → 0；熔断（supervisor_fused）与兜底收尸/收编超限放弃看护 → 75；crash 路径退出码不变

## 3. fenix_session 启停迁移

- [ ] 3.1 `core/fenix_session.py:start_daemon`：tmux session 创建退役；unit 缺失时生成安装并 `systemctl enable --now`；幂等 already 语义、`.fenix`/STATE.md 校验、systemctl 不可用可读错误全部保持
- [ ] 3.2 `core/fenix_session.py:stop_daemon` 双轨：unit 已装走 `systemctl stop --no-block` + 既有 ≤30s 轮询 + 超时对 /proc 残留进程补 SIGKILL；managed-but-no-unit 态保留既有直接信号链（写旗标→SIGTERM daemon→等待→超时 SIGKILL）不谎报成功；⑤ 无论成败清 `.fenix/stop` 与幂等语义保持；tmux kill-session 兜底退役
- [ ] 3.3 `fenix_session` 的 tmux 回退判定退役（`is_running`/`supervisor_running` 主判定扫 /proc 保持不变）

## 4. dashboard 承载迁移

- [ ] 4.1 `core/dashboard/server.py`：unit 承载实例（父进程 PID 1）纳入不可接管豁免，与 `_parent_is_tmux_server` 豁免并列——接管方获可读失败，生产实例不闪断
- [ ] 4.2 `core/hook_engine.py` 内置 `pushed → restart-dashboard` 执行侧迁 `systemctl restart fenix-dashboard`；unit 未安装时维持静默 skip（不报错不告警）；用户 config legacy `target` 键容忍存在不消费

## 5. 搬迁脚本与配方

- [ ] 5.1 新建 `bin/migrate_to_systemd.py`（支持 `--dry-run`）：① 写 unit 与 EnvironmentFile 候选稿（不 enable）② 旧语义专用路径拆旧 tmux 链 + 旧 dashboard 实例 kill pid 等端口释放（不复用迁移后启停函数）③ `systemctl enable --now` ④ 验收（进程/端口/退出码语义/env 冒烟）；dry-run 零副作用
- [ ] 5.2 `skills/fenix-setup/SKILL.md` 与 `skills/fenix-dashboard/SKILL.md` 配方 systemctl 化：托管启动、dashboard 启动/重启协议、看现场（journalctl + 既有日志文件）；新增「人工切换步骤」小节（env 候选稿审核 → dry-run → 真切换 → 验收 → 回滚配方），实际切换由人工执行

## 6. 测试与预演

- [ ] 6.1 新建 `tests/test_systemd_hosting.py`：unit 模板字段与安全化、幂等安装、退出码协议、denylist 过滤、stop 双轨、接管豁免、restart-dashboard skip（假 systemctl 注入 PATH 或 monkeypatch，不触真 systemd）
- [ ] 6.2 存量承载测试迁移：`tests/test_supervisor_hosting.py`（tmux 启动/停止断言改 systemctl 双轨）、`tests/test_daemon_lifecycle_races.py`、`tests/test_hook_engine.py`（restart-dashboard）、`tests/test_dashboard_orphan_guard.py`（接管豁免扩展）
- [ ] 6.3 `bin/migrate_to_systemd.py --dry-run` 对 fixture 项目根实跑预演（无副作用断言）+ 全量回归自查（新/改测试全绿）
