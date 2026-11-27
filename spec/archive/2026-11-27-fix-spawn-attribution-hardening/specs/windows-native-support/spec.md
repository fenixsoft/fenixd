# spec delta: fix-spawn-attribution-hardening

> 归属 capability：windows-native-support
> 完整规格见 spec/changes/windows-native-support/specs/windows-native-support/spec.md（活跃变更）
> 本文件为本次变更的 ADDED 增量。

## ADDED Requirements

### Requirement: harness CLI 解析单源化（预检与 spawn 同源）

Windows 上 agent harness CLI（`claude` 等）的可执行解析 MUST 单源化：spawn-spec
构建阶段 MUST 用 `shutil.which(executable)` 的解析结果替换 `argv[0]`（裸名不得直达
`CreateProcess`——Windows 对无扩展名可执行文件只自动补 `.exe`，npm 安装的 CLI 仅有
`.cmd/.ps1` shim）；argv[0] 替换仅 win32 生效（POSIX 裸名 execvp 已可 spawn，保持
Linux 逐位不变硬约束）；预检（`precheck_harness_executable`）MUST 消费同一解析结果。
which 解析失败时 MUST 走 `HARNESS_CLI_UNAVAILABLE_MARKER` fail-fast 路径。

#### Scenario: which 可见则 spawn 可达

- **WHEN** `shutil.which("claude")` 解析到 `claude.cmd`（PATHEXT 形态）
- **THEN** spawn argv[0] 为该解析绝对路径，`Popen` 成功拉起（不再 `WinError 2`）

#### Scenario: which 不可见则预检拦截

- **WHEN** PATH 中无 `claude` 任何 PATHEXT 形态
- **THEN** 预检产出 `HARNESS_CLI_UNAVAILABLE` 标记，不进入派发

### Requirement: 确定性 spawn 失败分类（infra-deterministic）

spawn 阶段的 `FileNotFoundError`（WinError 2/3，环境缺件）MUST 归类为
infra-deterministic 终态：不消耗 `impl_run_budget`、不进重试、不触发 arbiter 升级；
STATE error 字段 MUST 带根因与修复指引。run 失败归因 MUST 三型分立
（spawn 失败 / 非零退出 / 结果文件缺失），结果文件缺失时 MUST 附 run 转录
stderr 尾窗。

#### Scenario: 缺件 spawn 失败一跳终态

- **WHEN** spawn 抛 `FileNotFoundError: [WinError 2]`（claude 不在 PATH）
- **THEN** 该 run 立即终态（不重试、不冻结、不升级），error 含
  「claude 不在当前 PATH（§8 服务 PATH 最小集）」修复指引，预算计数不变

#### Scenario: 结果文件缺失带 stderr 尾窗

- **WHEN** run 异常结束且结果文件未产出
- **THEN** 归因记录附 run 转录 stderr 尾窗（非空串）

### Requirement: spec CLI schema 前置校验

`fenix_spec.py new` MUST 在写任何 `.spec.yaml` 前调用 `load_schema()` 校验
`schemas/spec-driven/schema.yaml` 可读；缺失时 fail-fast（退出非 0）并输出修复指引
（制品缺件 → 按 install.md §3A 注记补齐）。禁止出现「new 成功而 status 崩」的
半残脚手架。

#### Scenario: schema 缺失时 new 拒绝创建

- **WHEN** 部署面缺 `schemas/spec-driven/schema.yaml` 时运行 `fenix_spec.py new demo`
- **THEN** 退出非 0，不产生 `.spec.yaml`，输出含 schema 路径的修复指引

### Requirement: 运行时日志卫生

- 用户级配置「顶层不是对象，按空配置处理」MUST 为 DEBUG 级（注释-only 模板是
  设计内合法空配置）
- `os.getpgid`（POSIX-only）MUST 平台守卫（win32 不调用）
- dashboard MUST 在 handle_one_request 层吞掉 `ConnectionResetError`/
  客户端断连类异常（debug 留痕，不刷全栈 traceback）
- 框架源码含转义序列的 docstring MUST 用 raw string（Python 3.13 零 SyntaxWarning）

#### Scenario: 全新安装零噪音基线

- **WHEN** 全新安装（注释-only 用户配置）+ 一次冒烟派发（含客户端提前断连）
- **THEN** daemon 日志无「顶层不是对象」ERROR、无 getpgid WARNING、
  无 WinError 10054 traceback 刷屏

#### Scenario: Python 3.13 导入零 SyntaxWarning

- **WHEN** `python3 -W error::SyntaxWarning -c "import core"`（或全库编译检查）
- **THEN** 零 SyntaxWarning

### Requirement: daemon 服务环境注入与自检

`install_unit` MUST 支持 `env` 参数（`dict`）以**注册表 REG_MULTI_SZ 形态**写入
`AppEnvironmentExtra`（元素边界确定，禁 nssm set 多参数引号坑形态），写入 MUST 为
read-modify-write 合并（同键 K=V 覆盖、异键保留——install.md §8 手工配置的服务
PATH 最小集等既有条目不得被整值替换清除）；幂等重跑与安装完成路径 MUST 做服务环境
自检——以服务 PATH 视角解析 claude/git，解析失败在返回 JSON 报
`env_defect`（含缺失目录指引），不等派发烧三轮才暴露。

#### Scenario: env 注入一次配对

- **WHEN** `install_unit(root, env={"PATH": "<最小集>", "DSH_HOME": "..."})`
- **THEN** 服务注册表 Parameters/AppEnvironmentExtra 为 REG_MULTI_SZ 多元素，
  nssm restart 后服务内可见

#### Scenario: 服务环境缺陷提前暴露

- **WHEN** 幂等重跑时服务 PATH 无法解析 git 或 claude
- **THEN** 返回 JSON 含 `env_defect` 与缺失可执行指引
