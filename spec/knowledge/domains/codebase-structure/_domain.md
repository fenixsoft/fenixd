# 代码结构治理
> 最后更新：2026-11-13 01:32 UTC+8

core 后端代码的结构组织与结构类重构纪律：包分层、门面转发契约、巨型类与超长函数拆分。平台抽象层（PAL 单点分发、POSIX syscall 零散落守卫与 win32 双后端）也在此域。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [core 包职责分层结构](core-package-structure.md) | core/ 按组合提取+门面分层组织，外部 API 零变化 | 2026-10-03 04:59 |
| [门面转发契约](facade-forwarder-contract.md) | 三大门面 `__getattr__` 注册表转发的收敛边界与调用点覆盖硬门 | 2026-10-03 04:59 |
| [巨型类按职责拆分](giant-class-decomposition.md) | 三大巨型类拆子包/资源子路由的格局与兼容不变式 | 2026-10-03 04:59 |
| [超长函数拆分纪律](long-function-decomposition.md) | 超长函数拆私有方法、主函数收敛为编排骨架 | 2026-10-03 04:59 |
| [平台抽象层（PAL）](platform-abstraction.md) | core/platform/ 六组平台中立接口单点分发、POSIX syscall 零散落静态守卫、全库进程模型不变量（零 fork/multiprocessing）、Linux 行为零变化的向后兼容转发、win32 全后端（Job Object/CTRL_BREAK 分层终止、msvcrt 锁、NSSM 映射、退出码死法闭集与端口 EXCLUSIVEADDRUSE） | 2026-11-13 01:32 |
