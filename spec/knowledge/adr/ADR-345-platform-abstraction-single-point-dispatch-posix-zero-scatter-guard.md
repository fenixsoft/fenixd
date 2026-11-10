# ADR-345：平台抽象单点分发与 POSIX syscall 零散落守卫

date: 2026-11-11
status: accepted

## Context

fenixd 深度依赖 Linux 系统调用习惯（flock / procfs / systemd / 进程组信号 / pwd），无法在 Windows 上原生运行；部分开发者的 claude code 与 dsh 以 Windows 原生进程运行，fenix harness 定位为它们的增强，fenixd 须原生支持 Windows。POSIX 依赖真实分布盘点显示 core/ 内 flock 调用 78 处、`/proc/` 字面量 16 个文件、`start_new_session=` 词面 33 处/18 文件、平台判断分支散点存在——若直接在散落点上加平台分支，Windows 接入会把 core/ 变成双平台条件分支泥潭，且每处 syscall 语义漂移都无守卫可见。

## Decision

- **平台判断全库单点**：新增 `core/platform/` 包，`__init__.py` 按 `sys.platform` 选择后端（win32 → win32，其余一切形态 → linux 缺省后端），平台选择逻辑全库仅此一处；业务代码只允许 `from core.platform import api as pal` 消费，平台判定唯一合法替身是 `pal.IS_WINDOWS`。
- **POSIX syscall 零散落 + 零豁免静态守卫**：core/（唯一豁免 `core/platform/linux.py`）禁止 fcntl/pwd 导入、killpg/setsid 直调（含 from-import 变体）、start_new_session 关键字、prctl、`/proc/` 字面量——`/proc/` 按裸字面量口径断言字符串常量（覆盖单/双引号与 f-string；双引号前缀口径实测漏检 6/16 存量文件）。豁免只允许「双向钉计数」的渲染 payload / 测试缝形态；新增直接消费端一律迁 PAL，不以豁免换省事。
- **向后兼容转发保零回归**：proc_utils / fs_utils / systemd_hosting 公开签名原样保留、内部转发 PAL，存量调用点与字符串路径 patch 语义零改动；「Linux 行为零变化」是收敛的硬约束，验收 = 全量测试全绿且既有断言零修改（守卫测试除外）。
- **后端接口按目标后端预埋语义位**：B 组探活接口三态（alive/dead/unknown，Linux 后端不产生 unknown）、F 组 `pytest_timeout_method`（linux=signal / win32=thread），第二后端的实现空间在契约层已留位。

## Consequences

- core/ 后续任何 SPEC 不得新增 POSIX 散点或平台条件分支——回潮被静态守卫在合入前拦截（回潮即红并指认文件，违禁清单取证落 `.history/`）。
- Windows 后端在干净切口上实现：只写 `core/platform/win32.py`，不触碰业务代码；psutil / portalocker / pywin32 依赖走平台 extras，不进主依赖。
- 代价：新增平台能力须先在 `api.py` 扩契约再落 `linux.py`，比直调多一层；`/proc/` 渲染 payload（unit 注释行、environ 捕获错误文案）须登记钉计数豁免，计数漂移需人工核对同步。
- bin/ 脚本（fenixd_supervisor 等）的 POSIX 面不在守卫范围（守卫范围 = core/），其迁移属托管链范畴另行裁定。
