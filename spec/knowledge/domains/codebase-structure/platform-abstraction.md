# 平台抽象层（PAL）

<!-- knowledge: capability=platform-abstraction rev=1 sources=spec/changes/add-platform-abstraction-layer -->

`core/platform/` 是全库唯一的平台敏感实现收口点：六组平台中立接口（A–F）对业务代码屏蔽 Linux 系统调用习惯（flock / procfs / systemd / 进程组信号 / pwd），使 core/ 业务代码零平台分支、POSIX syscall 零散落；第二后端（Windows）可在干净切口上接入而 Linux 行为零变化。

## 规则

- **单点分发**：`core/platform/__init__.py` 是全库唯一含平台选择逻辑的模块——按 `sys.platform` 分发（win32 → `win32.py`，其余一切形态 → `linux.py` 缺省后端），选中的后端实现注入 `api` 模块命名空间；`pal` 既是六组接口契约（Protocol + 异常类型），也是业务消费门面。
- **业务消费形态**：core/ 业务代码只允许 `from core.platform import api as pal` 后经 pal 调用平台能力；平台判定的唯一合法替身是 `pal.IS_WINDOWS` 平台谓词。
- **六组接口面**：A 进程生命周期（`spawn_detached` / `run_detached` / `spawn_detached_async` / `terminate_graceful` / `kill_tree` / `bind_to_parent` / `kill_group_alive`）；B 进程情报（cmdline/stat/cwd/environ 解析、端口占用定位、`is_alive_with_identity` 身份锚定探活、`process_info` 含 start_token 防 PID 复用）；C 文件锁（`flock_exclusive` / `flock_release` / `try_lock` / `exclusive_lock`）；D 托管（`systemctl_available` / `run_systemctl` 单缝 + HostingProvider 六名 `install_unit`/`start`/`stop`/`is_running`/`env_file`/`logs_hint`）；E 环境/用户/文件系统（`home_dir` / `current_user` / `ensure_link` / `fsync_dir`）；F 测试基建（`pytest_timeout_method`）。
- **Linux 后端承载全部既有 Linux 行为语义**：A 组独立进程组 spawn、SIGTERM→宽限→SIGKILL 纪律、killpg + 拒自杀进程组守卫、PDEATHSIG 绑定父进程；B 组 /proc 解析语义、探活不可用维持 fail-closed（判 stopped）；D 组 systemd 全语义一字不动（`_run_systemctl` 单缝、Restart=on-failure + StartLimit + TimeoutStopSec=2100 + SuccessExitStatus=75、EnvironmentFile 0600 原子写、exit 75 豁免、stop 双轨）；E 组 HOME 单源（并入 git_env 凭证双腿）与 symlink 降级链。
- **B 组探活三态语义**：探活接口返回 alive / dead / unknown 三态；Linux 后端不产生 unknown（/proc 恒可用），该语义位为 psutil 类进程情报后端预埋，现行 fail-closed 行为不变。
- **向后兼容转发**：`proc_utils` / `fs_utils` / `systemd_hosting` 公开签名原样保留、内部转发 PAL——存量调用点与字符串路径 patch 语义零改动。
- **文件锁单源**：core/ 全部 flock 用法收敛 `fs_utils.with_file_lock` 单源（含 `FlockRotatingFileHandler`）；`with_file_lock` 以可选参数 `nonblocking` / `timeout_s` 承载非阻塞形态——默认值保持阻塞 `LOCK_EX` 行为不变；`nonblocking=True` 时仅对「锁被占」类 errno（EAGAIN/EACCES）按 50ms 步长限时重试，其它 errno 立即抛 `FileLockUnavailable`，限时未抢到抛 `FileLockBusy`（两因可区分、调用方可分别降级留痕）。五个 NB fail-fast 消费点（verify_scenarios / regression / verify_contract / dashboard server / verify_report）以显式传参保持立即返回不阻塞。
- **原子写单源**：跨模块原子写收敛 `fs_utils.atomic_write_text` 单一实现（mkstemp 唯一临时文件 + fsync + `os.replace`），热路径（runner / state_machine 等）不另建私有平行实现。
- **spawn 收敛**：core/ 的 detached spawn 面统一走 `pal.spawn_detached`（asyncio 子进程走 `spawn_detached_async`）；`new_session=False` 形态保留「不新建会话/进程组、信号直达直接子进程」的动态 passthrough 语义，不得盲改无条件 detached。
- **静态守卫（零豁免纪律）**：`tests/test_platform_guard.py` 以 AST 口径断言两类防回潮面——① POSIX 面：core/（唯一整文件豁免 `core/platform/linux.py`）零 `import fcntl`、`from fcntl import`、`import pwd`、`os.killpg(`、`from os import killpg`、`os.setsid(`、`start_new_session=`、`prctl`、`/proc/` 字面量（按裸字面量口径断言字符串常量，覆盖单/双引号与 f-string 形态、排除 docstring——双引号前缀口径存在漏检面）；② 平台判断面：core/（豁免整个 `core/platform/`）零 `sys.platform` / `platform.system` / `os.name` 属性访问，import 别名逃逸（如 `import sys as s`）经别名映射封堵。豁免面登记计数双向钉死（回潮或消失都判漂移须人工核对）：`/proc/` 渲染 payload 豁免 `systemd_hosting.py` 2 处、`start_new_session` 关键字豁免 `runner.py` 测试缝 shadow 转发 1 处（主树 Popen 形态契约保留，不构成 syscall 绕行通道）。新增直接消费端必须迁移到 PAL，不得以豁免清单换省事。
- **测试基建平台拆分**：pytest `timeout_method` 以 `pal.pytest_timeout_method()` 为单源（Linux 恒 `signal`，SIGALRM 硬门与 allowlist 机制不变；win32 恒 `thread` 属 Windows 后端范围）。
- **依赖面不变**：本层 Linux 面零新增第三方依赖；Windows 后端依赖（psutil / portalocker / pywin32）按平台 extras 由后续 SPEC 引入，不进主依赖。

## 关键行为

- 守卫测试失败时把违禁清单取证落 `.history/guard-posix-failure.json`（.gitignore 内，绿跑零副作用）——全量回归 pytest 详情临时文件消失后仍可读唯一违禁清单。
- 守卫对 core/ 全量 `ast.parse` 走进程级缓存（同一 pytest 进程内源文件不变），保障单用例 10s 超时硬门。
- `core/platform/win32.py` 为占位后端：接口与 linux.py 同名同签名，调用即抛 `NotImplementedError`；非 Windows 环境 `__init__.py` 不导入该模块。

## 代码锚点

- 主实现：`core/platform/`（`__init__.py` 单点分发、`api.py` 契约 + 门面、`linux.py` Linux 后端、`win32.py` 占位）
- 锁与原子写单源：`core/fs_utils.py`（`with_file_lock` / `atomic_write_text`）
- 转发消费端：`core/proc_utils.py`、`core/systemd_hosting.py`
- 守卫与契约测试：`tests/test_platform_guard.py`、`tests/test_platform_pal.py`
- 测试基建消费：`pytest.ini`（`timeout_method` 接 pal F 组）

## 溯源

- 2026-11-11 add-platform-abstraction-layer（spec/changes/add-platform-abstraction-layer/） — 新建本页：core/platform/ 六组 PAL API 与 Linux 后端、sys.platform 单点分发、proc_utils/fs_utils/systemd_hosting 转发化、flock 与原子写收敛单源、with_file_lock 非阻塞参数扩展、POSIX 面/平台判断面双静态守卫契约
