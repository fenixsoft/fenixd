# Proposal: add-platform-abstraction-layer

## Why

fenixd 深度依赖 Linux 系统调用习惯（flock / procfs / systemd / 进程组信号 / pwd），无法在 Windows 上以原生进程运行；而部分开发者的 claude code 与 dsh 以 Windows 原生进程运行，fenix harness 定位为它们的增强，fenixd 必须原生支持 Windows。按已批准的架构评估（`docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md`）与用户硬约束 2/3：先做架构层平台抽象 + Linux 实现收敛并合入主线，Windows 后端留待后续 SPEC 在干净切口上实现。

本 SPEC 是该路线的第一步（评估文档 §7 SPEC-1，工作项 W1–W7），行为契约：**Linux 上全部行为零变化**。

## What Changes

- **新增 `core/platform/` 包**：`api.py`（六组平台中立接口 A–F：进程生命周期 / 进程情报 / 文件锁 / 托管 HostingProvider / 环境用户文件系统 / 测试基建）+ `linux.py`（现有 Linux 行为逐条平移）+ `win32.py`（SPEC-2 占位）+ `__init__.py` 单点分发（`sys.platform` 判断全库仅此一处；业务代码只允许 `from core.platform import api as pal`）。
- **W1 flock 收敛**：core/ 78 处 `flock(` 收敛到 `fs_utils.with_file_lock` 单源（含 `FlockRotatingFileHandler`）。**前置**：`with_file_lock` 先扩展可选参数 `nonblocking` / `timeout_s`，默认值保持现行阻塞 LOCK_EX 行为不变（向后兼容）——否则五个 NB fail-fast 消费点（verify_scenarios / regression / verify_contract / dashboard server / verify_report）收敛即引入 Linux 挂死回归。
- **W2 原子写收敛**：5 份平行私有原子写实现（runner.py `_write_atomic`、claude_adapter.py、verify_scenarios.py、code_fix.py、state_machine.py）收敛到 fs_utils 单源。
- **W4 转发化**：`proc_utils` / `fs_utils` / `systemd_hosting` 公开签名原样保留、内部转发 PAL——存量 438 个测试文件调用点零改动。
- **W4b 直接消费端迁移（守卫零豁免的前提）**：core/ 16 个含 `/proc/` 字面量的文件全部迁移到 PAL B 组接口；`serving_registry.py` 的 `os.killpg(pid, 0)` 探活直调改走 PAL 探活接口。
- **W5 spawn 收敛**：core/ 33 处 `start_new_session=True` 改 `pal.spawn_detached`；`cli_runner.py` 两处 asyncio 子进程同批。
- **W6 守卫与顺手项**：新增静态守卫测试，断言 core/（除 `core/platform/linux.py`）零 `import fcntl` / `import pwd` / `os.killpg(` / `os.setsid(` / `start_new_session=` / `prctl` / `"/proc/` 字面量（沿用 guard_killpg 手法）；`event_bus.py` "inotify" 文档措辞修正（实为 2s checksum 轮询）；`install.sh` 退役的 tmux 依赖检查清理。
- **W7 测试基建**：pytest.ini 平台拆分（linux 路径零变化；win32 `thread` 方法属 SPEC-2）。
- **零新增第三方依赖**（win32 依赖 psutil/portalocker/pywin32 仅 SPEC-2 按平台 extras 引入）。
- **范围边界**：守卫与迁移范围 = `core/`；`bin/` 脚本（fenixd_supervisor 等）的 POSIX 面属 SPEC-2 托管链范畴，本 SPEC 不动。

## Capabilities

### New Capabilities

- `platform-abstraction`: 平台抽象层六组 PAL API 与 Linux 后端（行为 = 现有 Linux 实现逐条平移），以及「POSIX syscall 零散落于 core/」的静态守卫契约。

### Modified Capabilities

（无——本 SPEC 为行为保持重构，不修改任何既有能力的 spec 级 REQUIREMENT；systemd-hosting / supervisor-hosting / verify-process-lifecycle 等既有能力契约保持原样。）

## Impact

- **新增**：`core/platform/`（api.py / linux.py / win32.py 占位 / __init__.py）、`tests/test_platform_guard.py`、`tests/test_platform_pal.py`。
- **修改**：core/ 约 40 个文件（W1 19 文件 flock 面、W2 5 文件原子写、W4b 16 文件 /proc 面、W5 24 文件 spawn 面，并集清单见 design.md）+ `pytest.ini` + `install.sh` + `core/event_bus.py` 措辞。
- **行为契约**：Linux 全部行为零变化；SPEC-0（`fix-legacy-test-failures`）清零存量失败后，本 SPEC 验收 = 438 个测试文件全量绿且断言零修改（守卫测试除外）。
- **依赖关系**：`depends_on: fix-legacy-test-failures`（SPEC-0 先行清零存量失败，用户定夺 2026-11-10）。
- **知识依据**：`spec/knowledge/_inbox/posix-dependency-true-distribution-1110.md`（POSIX 依赖真实分布盘点）、评估文档 §4 现状盘点 / §5 PAL 设计 / §8 风险登记。
