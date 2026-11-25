# platform-abstraction

## ADDED Requirements

### Requirement: 平台判断全库单点分发
系统 SHALL 提供唯一包 `core/platform/`：`__init__.py` 按 `sys.platform` 选择后端（Linux → `linux.py`），平台判断全库 MUST 仅存在于该文件一处；业务代码 MUST 以 `from core.platform import api as pal` 消费，MUST NOT 在业务代码中出现平台条件分支。

#### Scenario: 业务代码零平台分支
- **WHEN** 静态扫描 core/（除 `core/platform/`）中的 `sys.platform`、`platform.system`、`os.name` 判断
- **THEN** 命中数为 0

#### Scenario: 后端选择唯一
- **WHEN** 在 Linux 上 import `core.platform`
- **THEN** `pal` 暴露的实现对齐 `linux.py`，且 `core/platform/__init__.py` 是唯一含平台选择逻辑的模块

### Requirement: PAL A 组进程生命周期接口
系统 SHALL 提供进程生命周期接口：`spawn_detached(cmd, cwd, env, *, new_session=True) -> Popen`、`terminate_graceful(proc, grace_s)`、`kill_tree(pid_or_proc, caller)`、`bind_to_parent(child)`。Linux 后端 MUST 逐条平移现行语义：`start_new_session=True` spawn 面、`new_session=False` 形态（runner.py:7030 `spawn_spec.start_new_session` 动态 passthrough：无独立进程组、SIGTERM 直杀直接子进程）、SIGTERM→grace→SIGKILL 纪律、killpg + 拒自杀进程组守卫（guard_killpg 语义）、PDEATHSIG（dashboard/server.py:597 现行为）。

#### Scenario: spawn_detached 等价 start_new_session
- **WHEN** 以 `pal.spawn_detached` 启动一个脱离会话的子进程
- **THEN** 子进程行为与现行 `subprocess.Popen(..., start_new_session=True)` 等价（新会话、脱离父进程组）

#### Scenario: new_session=False 保留直杀子进程语义
- **WHEN** 以 `new_session=False` 调用 `pal.spawn_detached`（runner.py:7030 的 `spawn_spec.start_new_session` 动态 passthrough 平移路径）
- **THEN** 子进程不新建会话/进程组（对齐现行 `start_new_session=False` 语义），SIGTERM 直达直接子进程，行为与迁移前逐位一致

#### Scenario: kill_tree 保留拒自杀守卫
- **WHEN** 调用 `pal.kill_tree` 且目标为调用者自身所在进程组
- **THEN** 拒绝执行（对齐现行 `guard_killpg` 语义），不向自身发信号

### Requirement: PAL B 组进程情报接口（fail-closed 语义保留）
系统 SHALL 提供进程情报接口：`process_info(pid)`（含 start_token 防 PID 复用）、`is_alive_with_identity(pid, identity)`、`find_port_owner(port)`、`parent_comm(ppid)`、`process_environ(pid)`。Linux 后端 MUST 平移现行 /proc 解析语义；探活不可用 MUST 维持现行 fail-closed（判 stopped）语义。

#### Scenario: 身份锚定语义不变
- **WHEN** 对已知进程调用 `is_alive_with_identity(pid, identity)`
- **THEN** 判定结果与现行 cwd+cmdline 锚定实现一致（fenix_session / serving_registry / locks 共用语义）

#### Scenario: 端口定位无 lsof 依赖
- **WHEN** 调用 `find_port_owner(port)` 查询监听端口占用者
- **THEN** Linux 后端按现行 /proc/net/tcp inode+fd 扫描实现（dashboard/server.py:213-267 平移），不引入新外部命令依赖

### Requirement: PAL C 组文件锁与 with_file_lock 向后兼容扩展
系统 SHALL 将 core/ 全部 `flock(` 用法（grep 词面 78 处，含极少量注释词面，以真实调用位点为准）收敛到 `fs_utils.with_file_lock` 单源（含 `FlockRotatingFileHandler`），并提供 `exclusive_lock(path, timeout_s)` / `try_lock(path)` PAL 接口。`with_file_lock` MUST 新增可选参数 `nonblocking` / `timeout_s`，默认值 MUST 保持现行阻塞 LOCK_EX 行为不变；五个 NB fail-fast 消费点（verify_scenarios / regression / verify_contract / dashboard server / verify_report）MUST 以显式参数保持非阻塞语义。

#### Scenario: 默认参数行为不变
- **WHEN** 以无新参形式调用 `with_file_lock(path, fn)`
- **THEN** 行为与现行阻塞 LOCK_EX 语义完全一致（既有测试断言零修改通过）

#### Scenario: NB fail-fast 语义保持
- **WHEN** 锁被占用时以 `nonblocking=True` 调用（五个 NB 消费点路径）
- **THEN** 立即返回失败不阻塞（对齐现行 `LOCK_EX | LOCK_NB` 行为），回归测试无挂死

### Requirement: PAL D 组托管接口 systemd 语义一字不动
系统 SHALL 提供托管 HostingProvider 接口（`install_unit / start / stop / is_running / env_file / logs_hint`），Linux 后端 MUST 平移 systemd 全语义（`_run_systemctl` 单缝、Restart=on-failure + StartLimit + TimeoutStopSec=2100 + SuccessExitStatus=75 + KillMode=mixed、EnvironmentFile 0600 原子写、exit 75 豁免、stop 双轨），MUST NOT 改变任何 systemd 行为。

#### Scenario: unit 渲染语义不变
- **WHEN** 渲染项目 unit 文件
- **THEN** 字段与现行 `render_project_unit` 输出一致（既有 test_systemd_hosting 断言零修改通过）

#### Scenario: environ 捕获语义不变
- **WHEN** 捕获 systemd 服务进程环境（`/proc/<pid>/environ` 候选稿路径）
- **THEN** 行为与现行 systemd_hosting.py:184 实现一致

### Requirement: PAL E 组环境/用户/文件系统接口
系统 SHALL 提供 `home_dir()`（HOME 单源，并入 git_env 凭证双腿）、`current_user()`、`ensure_link(src, dst)`（symlink 降级链）、O_DIRECTORY 处理。Linux 后端 MUST 保持现行行为：git_env.py 用户名推导、claude_adapter symlink 安装语义不变。

#### Scenario: git_env 语义不变
- **WHEN** 推导 git 子进程用户名
- **THEN** 结果与现行 core/git_env.py:21 实现一致（既有测试断言零修改通过）

### Requirement: 测试基建平台拆分 linux 零变化
pytest 配置 MUST 完成平台拆分：Linux 路径 MUST 保持 `timeout_method = signal` 零变化，`tests/timeout-allowlist.yaml` 机制不变；win32 `thread` 方法属 SPEC-2，不在本 SPEC 范围。

#### Scenario: pytest.ini linux 行为不变
- **WHEN** 在 Linux 上运行 pytest
- **THEN** timeout 门行为与现行完全一致（10s 硬门 + SIGALRM + allowlist 机制）

### Requirement: POSIX syscall 零散落静态守卫
系统 SHALL 新增静态守卫测试：断言 core/（唯一豁免 `core/platform/linux.py`）零 `import fcntl`、零 `from fcntl import`、零 `import pwd`、零 `os.killpg(`、零 `from os import killpg`、零 `os.setsid(`、零 `start_new_session=`、零 `prctl`、零 `/proc/` 字面量（`/proc/` 按裸字面量口径断言字符串，覆盖单/双引号与 f-string 形态——存量 16 个命中文件中 6 个不以双引号前缀形态出现，双引号口径守卫会漏检；from-import 变体防 import 形态逃逸）。守卫 MUST 零豁免清单——所有直接消费端（16 个含 `/proc/` 字面量文件、`serving_registry.py` 的 `os.killpg(pid, 0)` 探活直调）MUST 在本 SPEC 内迁移到 PAL，不以豁免换省事。守卫启用 MUST 排在 W4b 迁移完成之后。

#### Scenario: 守卫在迁移后全绿
- **WHEN** W4b 迁移完成后运行守卫测试
- **THEN** core/ 除 `core/platform/linux.py` 外对上述七类模式命中数为 0

#### Scenario: 回潮即红
- **WHEN** 向 core/ 任一业务文件新增 `import fcntl` 并运行守卫测试
- **THEN** 守卫测试失败并指认该文件

### Requirement: Linux 行为零变化与全量绿验收
本 SPEC MUST 保持 Linux 全部行为零变化：proc_utils / fs_utils / systemd_hosting 公开签名原样保留（内部转发 PAL）；SPEC-0（fix-legacy-test-failures）清零存量失败后，验收 MUST 为全量测试（438 个测试文件）全绿且既有断言零修改（守卫测试除外）；MUST 零新增第三方依赖。

#### Scenario: 全量回归零新增失败
- **WHEN** 在 SPEC-0 完成后的基线上运行 `python3 -m pytest tests/ -q`
- **THEN** 0 failed（全绿），且 `git diff` 显示既有测试文件断言零修改（守卫测试除外）

#### Scenario: 依赖面不变
- **WHEN** 检查 pyproject/requirements 变更
- **THEN** 零新增第三方依赖（win32 依赖属 SPEC-2 平台 extras）
