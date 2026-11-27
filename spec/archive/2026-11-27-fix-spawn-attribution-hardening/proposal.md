# Proposal: fix-spawn-attribution-hardening

## Why

v0.1.1 真机部署实测（Windows 11，附件 fenixd-install-feedback.md）暴露两类 P0：
①Windows 上 `claude` spawn 与预检**解析不同源**——`shutil.which("claude")` 按 PATHEXT
找到 `.cmd` shim 判"可用"，而 `CreateProcess` 对裸名只补 `.exe`，npm 安装的 Claude Code
无 `.exe` shim → 预检放行、spawn 必败（`WinError 2`）；确定性失败又走完整 fast-track
3 轮重试 → 冻结 → arbiter 升级（arbiter 车道同根因秒挂）——**三连烧且 error 字段不带根因**，
fail-fast 标记机制（`HARNESS_CLI_UNAVAILABLE_MARKER`）整条失效。
②制品侧 v0.1.1 缺 `schemas/` 暴露 CLI 校验不一致：`fenix_spec.py new` 不校验 schema 能
成功、`status` 才崩——半残脚手架。（打包面 schemas/vendor 已随 v0.1.2 落地，本 SPEC 只收
CLI 前置校验。）
另有三类日志/卫生噪音（A5/A6）与一处能力缺口（A7 服务环境注入），一并收口。

## What Changes

- **C-A3（P0，spawn 解析单源化）**：spawn-spec 构建阶段用 `shutil.which(executable)`
  的结果**替换** `argv[0]`（`core/agent_runner/harness/claude_adapter.py:409` 现为裸名
  `"claude"`；替换仅 win32 生效，见兼容性段）；预检与 spawn 消费同一解析结果——which 能找到的就是能 spawn 的，
  `HARNESS_CLI_UNAVAILABLE_MARKER` fail-fast 恢复有效。dsh 通道已有 .cmd shim 包裹链路
  （dsh 工具侧实现，fenixd 仓库无对应专名，仅作正交性注记），本改动与其正交
  （claude 通道补齐同等级的 Windows 生存能力）。
- **C-A4（P0，失败分类与归因）**：spawn 阶段 `FileNotFoundError`（`WinError 2/3`）归类
  `infra-deterministic`——不消耗 `impl_run_budget`、不进重试、不触发 arbiter，第一跳产出
  带修复指引的终态告警；run 失败归因三型分立（spawn 失败 / 非零退出 / 结果文件缺失），
  结果文件缺失时附 run 转录 stderr 尾窗（本次实测 stderr_tail 为空串，取证断链）。
- **C-A1r（CLI 前置校验）**：`fenix_spec.py new` 写 `.spec.yaml` 前先调 `load_schema()`
  （`core/spec_gen.py`），schema 缺失 fail-fast + 修复指引（与 status 同一完整性口径，
  杜绝半残脚手架）。
- **C-A5（日志卫生）**：用户级配置"顶层不是对象，按空配置处理"从 ERROR 降 DEBUG
  （注释-only 模板是设计内合法空配置，非错误）。
- **C-A6（Windows 卫生三件）**：`os.getpgid` 平台守卫（POSIX-only，win32 分支跳过）；
  dashboard `ConnectionResetError [WinError 10054]` 在 handle_one_request 层静音
  （debug 留痕，防 err 日志膨胀）；框架源码 docstring `r"""` 化消 SyntaxWarning
  （Python 3.13 每次 import 十几条，污染安装器输出与 daemon 日志）。
- **C-A7（能力）**：`install_unit(root, env=None)` 支持 `AppEnvironmentExtra` 注入
  （**注册表 REG_MULTI_SZ 形态**，元素边界确定）；幂等重跑时做服务环境自检
  （以服务 PATH 视角解析 claude/git，解析不到在返回 JSON 报 `env_defect`）。

## Capabilities

### Modified: windows-native-support（活跃变更 spec/changes/windows-native-support/specs/）

- 新增 ADDED Requirement：harness CLI 解析单源化、确定性 spawn 失败分类、
  spec CLI schema 前置校验、日志卫生（空配置降级/连接重置静音/平台守卫）、
  daemon 服务环境注入与自检。

## Impact

- 代码：`core/agent_runner/harness/claude_adapter.py`（argv 解析）；dispatch/归因层
  （`core/agent_runner/` 失败分类与 error 字段）；`bin/fenix_spec.py` +
  `core/spec_gen.py`（schema 前置）；`core/config.py` 或用户配置 loader（日志降级）；
  `core/dashboard/server.py` DashboardHandler（ConnectionReset 静音）；
  `core/proc_utils.py` kill_process_group（getpgid 平台守卫——全库唯一调用点）；
  `core/platform/win32.py install_unit`（env 注入 + 自检）；全库 docstring r-string
  机械批改。
- **过机复验铁则适用**：C-A3 改 spawn 契约（进程 API 面）、C-A7 改 NSSM 参数写入
  （服务承载面）——**不做**过机豁免声明，收口必须含 Windows 过机复验
  （dockur win-test 通道，§tests/integration/windows 纪律）；C-A1r/A5/A6 属日志与
  校验路径，可 Linux 契约测试收口。
- 兼容性：无 breaking；Linux 行为**逐位不变**——argv[0] 替换仅 win32 生效（POSIX 裸名经
  execvp/shebang 已可 spawn；全平台替换会引入 parent-env which 与 child-env PATH 查找的
  源漂移，并使 SpawnSpec 快照金样本失配，违反 windows-native-support 硬约束 1）。
  Windows 上 argv[0] 为 which 解析的 .cmd 绝对路径。
- 文档：§8 服务 PATH 最小集已随 v0.1.2 落地（本 SPEC 的 env 注入落地后补一句
  "可用 install_unit env= 一句话完成"）。
