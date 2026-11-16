# ADR-357：harness CLI 可执行解析单源——预检与 spawn 同源，argv[0] 替换仅 win32

date: 2026-11-16
status: accepted

## Context

Windows 真机部署实测暴露预检与 spawn 解析不同源：预检以 `shutil.which` 按 PATHEXT 找到 npm 安装 CLI 的 `.cmd` shim 判「可达」，spawn 却以裸名直达 `CreateProcess`——Windows 对无扩展名可执行文件只自动补 `.exe`，不认 `.cmd/.ps1` shim。结果预检放行、spawn 必败（`WinError 2`）：可达性结论与 spawn 实况脱钩，`HARNESS_CLI_UNAVAILABLE_MARKER` fail-fast 机制对这类环境整条失效，失败还被下游当瞬时故障处理（处置范式另见 ADR-358）。

## Decision

- 可执行解析单源 helper（`resolve_harness_executable`，`shutil.which` 透传）：spawn-spec 构建与预检（`precheck_harness_executable`）消费同一解析结果——「which 能找到的就是能 spawn 的」；预检不得独立 which 判定。
- 解析到即以解析结果替换 spawn argv[0]（Windows 上为 `.cmd` 绝对路径，CreateProcess 经 .cmd 文件关联原生拉起）；解析不到走既有 `HARNESS_CLI_UNAVAILABLE_MARKER` fail-fast 路径，不新增平行通道。
- argv[0] 替换仅 win32 生效：POSIX 裸名经 execvp/shebang 已可 spawn，全平台替换不改变可达性，却引入 parent-env which 与 child-env PATH 查找的源漂移，并使 SpawnSpec 快照金样本失配——Linux 逐位不变硬约束优先。
- 后续新增 harness adapter 的 spawn 路径一律消费同一解析 helper，禁止裸名直达 `CreateProcess`。

## Consequences

- Windows 上 npm 安装的 CLI（仅 `.cmd/.ps1` shim）spawn 可达，预检结论与 spawn 实况恒一致，fail-fast 恢复有效。
- `.cmd` shim 由 cmd.exe 再解释参数（BatBadBut 类攻击面）：argv 注入沿用既有 list2cmdline 口径，参数面扩展须在该口径内演进，不单独豁免。
- POSIX 侧 SpawnSpec 快照测试零触碰，Linux 全量行为逐位不变；dsh 通道的 .cmd shim 包裹链路（dsh 工具侧实现）与本机制正交并存。
