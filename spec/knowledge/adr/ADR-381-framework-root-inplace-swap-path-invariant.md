# ADR-381：框架根路径不变量——原地同盘 rename 三段式换装

date: 2026-11-25
status: accepted

## Context

框架安装上存在大面积根路径依赖：既有项目 `.fenix/` 骨架内的 fenixd.py/core 链接与 skills 软链全部以框架根绝对路径为目标；dashboard 与各项目 daemon 均自框架根加载代码、持目录句柄（Windows 下 CWD/句柄占用使运行中目录无法 rename）。更新时动摇根路径的两种直觉方案都不可行：迁新根路径 + 重跑 installer 刷新全部链接 = 存量项目骨架链接全断、迁移面不可控；原地 tar 覆盖 = 中断留下半新半旧混合态，且 Windows 被占用文件 PermissionError 面大。

## Decision

1. 框架根路径是不变量：换装必须在原根就位。流程为「停全部服务化进程 → 旧根同盘 rename 为 `<原名>.old-<ts>` 保留一代 → staging rename 为框架根 → 按 stop 逆序起回全部 unit」。
2. 停步 MUST 覆盖同一框架安装上的全部服务化进程（N 个项目 daemon unit 逐一经 PAL hosting 链解析 + dashboard unit 一并 stop；未服务化场景跳过停步并在结果注明）——不停全则 Windows 下 rename 确定性失败、Linux 下运行中进程会把日志/静态文件写进被换走的 `.old` 旧 inode。
3. staging 目录 MUST 与框架根同盘（框架根同级 `<parent>/fenixd-update-staging-<ts>/`），保证 rename 原子性。
4. 根路径不变使既有项目骨架链接与 skills 软链全部原地有效，installer 不重跑；用户级 `~/.fenix/` 与项目 `.fenix/` 不在任何更新写路径上，内容零改写。
5. 禁止迁新根 + 重跑 installer 路线；禁止原地 tar 覆盖路线。任一步失败 `.old-<ts>` rename 回原名回滚并重启 daemon；回滚副本仅保留一代，成功换装后清理更旧代。

## Consequences

- 更新零迁移成本：用户级配置与项目骨架天然保留，软链/PATH 无需刷新。
- 换装窗口 = 全部服务化进程的确定性停机窗；在飞 run 预检（存在在飞 run 拒绝执行）是该窗口的前置门。
- 换装后运行中进程内存代码仍为旧版（自洽），前端 dist 需刷新/重启 dashboard 加载——文档与更新结果必须携带该提示。
- 中断残留（staging/`.old-*`）由下一次编排幂等恢复（按状态续走或回滚），编排启动必须先做残留检测。
