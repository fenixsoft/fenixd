# Tasks: add-platform-abstraction-layer

## Deliverables

```yaml
- path: core/platform/__init__.py
  kind: new
- path: core/platform/api.py
  kind: new
- path: core/platform/linux.py
  kind: new
- path: core/platform/win32.py
  kind: new
- path: tests/test_platform_guard.py
  kind: new
- path: tests/test_platform_pal.py
  kind: new
- path: core/fs_utils.py
  kind: modify
- path: core/proc_utils.py
  kind: modify
- path: core/systemd_hosting.py
  kind: modify
- path: core/git_env.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/logger.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/deliverables.py
  kind: modify
- path: core/hook_engine.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_audit.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: core/serving_registry.py
  kind: modify
- path: core/verify_contract.py
  kind: modify
- path: core/verify_report.py
  kind: modify
- path: core/verify_scenarios.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: core/fenix_session.py
  kind: modify
- path: core/v2_dev_server.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/data/admin_stray_wip.py
  kind: modify
- path: core/dashboard/prototype_io.py
  kind: modify
- path: core/dashboard/ocr_status.py
  kind: modify
- path: core/dashboard/routes/architecture_routes.py
  kind: modify
- path: core/dashboard/routes/project_routes.py
  kind: modify
- path: core/dashboard/routes/regression_routes.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/harness/claude_adapter.py
  kind: modify
- path: core/agent_runner/harness/protocol.py
  kind: modify
- path: core/agent_runner/harness/one_shot.py
  kind: modify
- path: core/verify_engine/cli_runner.py
  kind: modify
- path: core/pm_engine/verification/serving.py
  kind: modify
- path: core/pm_engine/verification/serving_reclaim.py
  kind: modify
- path: core/worktree_manager/locks.py
  kind: modify
- path: core/worktree_manager/dist_conflicts.py
  kind: modify
- path: pytest.ini
  kind: modify
- path: install.sh
  kind: modify
```

## 1. W1+W2 锁与原子写收敛（可先行，纯 Linux 收敛）

- [x] 1.1 `core/fs_utils.py` `with_file_lock` 扩展可选参数 `nonblocking` / `timeout_s`，默认值保持现行阻塞 LOCK_EX 行为不变，新增单测覆盖默认/NB/超时三形态（放 `tests/test_platform_pal.py`）
- [x] 1.2 五个 NB fail-fast 消费点显式传参迁移保持非阻塞语义：`core/verify_scenarios.py`、`core/regression.py`、`core/verify_contract.py`、`core/dashboard/server.py`、`core/verify_report.py`
- [ ] 1.3 其余 13 个 fcntl 文件的自持 `open+flock` 全部收敛到 `with_file_lock` 单源（逐点核对 LOCK_EX|LOCK_NB 语义）：`core/admin_store.py`、`core/agent_runner/maintenance_runs.py`、`core/code_review.py`、`core/dashboard/data/admin_stray_wip.py`、`core/dashboard/prototype_io.py`、`core/deliverables.py`、`core/hook_engine.py`、`core/knowledge_audit.py`、`core/knowledge_backfill.py`、`core/knowledge.py`、`core/logger.py`（FlockRotatingFileHandler）、`core/serving_registry.py`、`core/state_machine.py`。注：`verify_contract.py` 不在此列——其唯一 flock 位点 `:1431` 即 NB 位点（`:1477` LOCK_UN 配对），归 1.2 显式 `nonblocking=True` 处置，双重归属会造成 NB→阻塞翻转歧义（design 风险 #1）；grep `flock(` 词面计数含注释词面（如 judge_gate.py:169），以真实调用位点为准全量收敛
- [ ] 1.4 W2 原子写 5 份平行实现收敛到 fs_utils 单源：`core/agent_runner/runner.py`（`_write_atomic`:6468）、`core/agent_runner/harness/claude_adapter.py`（:166）、`core/verify_scenarios.py`（:401）、`core/code_fix.py`（:276）、`core/state_machine.py`（:2951）

## 2. W3 PAL 骨架

- [ ] 2.1 新建 `core/platform/`：`api.py` 六组接口（A 进程生命周期 / B 进程情报 / C 文件锁 / D 托管 HostingProvider / E 环境用户文件系统 / F 测试基建锚点）+ `linux.py`（既有行为逐条平移）+ `win32.py`（SPEC-2 占位）+ `__init__.py`（sys.platform 单点分发）
- [ ] 2.2 新建 `tests/test_platform_pal.py`：A–E 组接口行为对齐单测（spawn_detached 等价 start_new_session、kill_tree 拒自杀守卫、B 组身份锚定/fail-closed、C 组三形态、D 组 systemd 语义锚点、E 组 home/user/link）

## 3. W4 单源转发化

- [ ] 3.1 `core/proc_utils.py`（kill_process_group/guard_killpg 公开签名不动，内部转发 pal.kill_tree；os.killpg:390 迁入 linux.py）、`core/fs_utils.py`（flock 原语转发 pal C 组）、`core/systemd_hosting.py`（_run_systemctl/unit 渲染/environ 捕获转发 pal D 组，systemd 全语义一字不动）
- [ ] 3.2 `core/git_env.py` home/current_user 并入 pal E 组（pwd:21 迁入 linux.py，公开行为不变）

## 4. W4b 直接消费端迁移（守卫零豁免前提）

- [ ] 4.1 16 个含 `"/proc/` 字面量文件全部迁移到 pal B 组接口：`core/dashboard/server.py`（探活/端口定位:213-267/父comm:401/PDEATHSIG:597）、`core/v2_dev_server.py`、`core/fenix_session.py`、`core/agent_runner/maintenance_runs.py`、`core/agent_runner/liveness.py`（:727）、`core/agent_runner/runner.py`、`core/agent_runner/harness/claude_adapter.py`、`core/agent_runner/harness/protocol.py`、`core/serving_registry.py`、`core/worktree_manager/locks.py`、`core/pm_engine/verification/serving_reclaim.py`、`core/adjudication_narrative.py`、`core/knowledge.py`、`core/knowledge_backfill.py`、`core/proc_utils.py`、`core/systemd_hosting.py`（:184 environ）
- [ ] 4.2 `core/serving_registry.py:482/502` 的 `os.killpg(pid, 0)` 探活直调改走 pal 探活接口（fail-closed 语义不变）
- [ ] 4.3 `core/dashboard/data/admin_stray_wip.py:1149` 的 `os.name == "nt"` 平台分支迁出业务代码（spec「业务代码零平台分支」静态扫描的现存唯二命中 :1143/:1149，无本任务则该场景验收必红）：经 pal 平台谓词或 linux.py 等价平移，Linux 判定恒 False 行为不变

## 5. W5 spawn 收敛

- [ ] 5.1 core/ `start_new_session` spawn 面收敛改 `pal.spawn_detached`：grep 词面 33 处（= 31 处 `=True` 调用位点 + runner.py:7030 动态 passthrough + :6793 注释词面），实改位点分布在 18 文件：`core/adjudication_narrative.py`、`core/agent_runner/liveness.py`、`core/agent_runner/maintenance_runs.py`、`core/agent_runner/runner.py`、`core/dashboard/ocr_status.py`、`core/dashboard/routes/architecture_routes.py`、`core/dashboard/routes/project_routes.py`、`core/dashboard/routes/regression_routes.py`、`core/dashboard/server.py`、`core/hook_engine.py`、`core/knowledge.py`、`core/pm_engine/verification/serving.py`、`core/proc_utils.py`、`core/regression.py`、`core/v2_dev_server.py`、`core/verify_contract.py`、`core/worktree_manager/dist_conflicts.py`、`core/verify_engine/cli_runner.py`。**特别约束**：runner.py:7030 的 `start_new_session=spawn_spec.start_new_session` 是动态 passthrough（False = 无独立进程组、SIGTERM 直杀直接子进程语义，见 :6793 注释），MUST 经 `spawn_detached(..., new_session=...)` 参数形态保语义迁移，MUST NOT 盲改为无条件 detached（否则 Linux 行为变化、违反零变化契约）；`harness/one_shot.py` 与 `harness/protocol.py` 零字面位点（其 spawn 经 harness 通道、无 start_new_session 参数），不在清单内
- [ ] 5.2 `core/verify_engine/cli_runner.py:405/415` 两处 asyncio 子进程迁移（pal.spawn_detached 异步形态或平台中立等价物）

## 6. W6+W7 守卫与收尾（必须排在 §4/§5 之后）

- [ ] 6.1 新建 `tests/test_platform_guard.py`，两组断言（断言调用/导入语法与字符串字面量，非注释词面）：① POSIX 面——core/（唯一豁免 `core/platform/linux.py`）零 `import fcntl`、`from fcntl import`、`import pwd`、`os.killpg(`、`from os import killpg`、`os.setsid(`、`start_new_session=`、`prctl`、`/proc/`（`/proc/` 按裸字面量口径断言字符串——存量 16 个命中文件中 6 个为单引号/f-string 形态，双引号前缀口径实测仅命中 10 个、会漏检回潮）；② 平台判断面——core/（豁免整个 `core/platform/`，`__init__.py` 单点分发为设计内唯一分支点）零 `sys.platform` / `platform.system` / `os.name` 判断（spec Requirement 1「业务代码零平台分支」场景的守卫执行面）
- [ ] 6.2 `core/event_bus.py` "inotify" 文档措辞修正（实为 2s checksum 轮询；措辞词面位于 :4/:56/:156，:1059 为 `_watch_loop` 定义锚）；`install.sh` 退役 tmux 依赖检查清理（:44）；`pytest.ini` 平台拆分锚点（linux 路径零变化）

## 7. 验收自检

- [ ] 7.1 运行 `python3 -m pytest tests/ -q` 全量回归零失败（438 个测试文件全绿，既有断言零修改，守卫测试除外）
- [ ] 7.2 自检 `core/platform/linux.py` 与被平移源实现逐条对照表（接口→源位置→平移说明）写入 PR 描述或 `core/platform/linux.py` 模块 docstring；确认 pyproject/requirements 零新增第三方依赖
