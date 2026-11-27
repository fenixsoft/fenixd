# Design: fix-spawn-attribution-hardening

> 归属变更：fix-spawn-attribution-hardening（fast-track）
> 上游输入：v0.1.1 部署实录反馈 A1r/A3/A4/A5/A6/A7
> 基线约束：spec/knowledge/domains/daemon-runtime/windows-native-support.md
> —— Linux 零变化硬约束；**过机复验铁则**：C-A3（spawn 契约）与 C-A7（NSSM 参数面）
> 属进程 API/服务承载面，**必须过机复验收口**（dockur win-test，tests/integration/windows
> 纪律），不做豁免声明。

## 决策

### D1 — spawn argv 解析单源化（A3）

`_build_spawn_spec`（claude_adapter.py）构建 argv 时：
`resolved = shutil.which(argv0)`；解析到 → `argv[0] = resolved`（Windows 上是
`.cmd` 绝对路径，`Popen(["C:\\...\\claude.cmd", ...])` CreateProcess 可原生拉起——
cmd shim 由 CreateProcess 的 .cmd 关联处理）；解析不到 → 返回 None，
上层走既有 `HARNESS_CLI_UNAVAILABLE_MARKER` fail-fast 路径。argv[0] 替换**仅 win32
生效**：POSIX 裸名经 execvp/shebang 已可 spawn，替换不改变可达性却引入 parent-env
which 与 child-env PATH 查找的源漂移，并使 SpawnSpec 快照金样本
（tests/test_harness_claude_snapshot.py）失配——违反基线硬约束 1「Linux 逐位不变」。
实现注记：.cmd shim 由 cmd.exe 再解释参数（BatBadBut 类面），argv 注入沿用既有
list2cmdline 口径，本 SPEC 不扩面。
`precheck_harness_executable`（harness/__init__.py:151）改为复用同一解析函数
（提取公共 helper，预检不独立 which）。与 dsh 通道 .cmd shim 链路正交（dsh 工具侧
实现，fenixd 仓库无对应专名）：该链路处理 npm .cmd shim 的 dsh 侧 spawn，本决策处理
claude 侧。

### D2 — 确定性失败分类（A4）

dispatch 层捕 `FileNotFoundError` 且 errno ∈ {2,3}（spawn 缺件）→ 归类
`infra-deterministic`：置终态 error（含「<exe> 不在当前 PATH——按 install.md §8
服务 PATH 最小集补齐后 nssm restart」指引）、**不递减** impl_run_budget、
跳过重试与 arbiter 升级。归因三型枚举：`spawn_failed` / `nonzero_exit` /
`result_missing`；`result_missing` 时归因附 run 转录 stderr 尾窗（截尾 2KB）。
错误分类表挂在 core/agent_runner 失败建模处（现实现把一切 run 异常都按
可重试处理——正是三连烧根因）。

### D3 — fenix_spec new schema 前置（A1r）

`new` 子命令入口（写 .spec.yaml 前）调 `core/spec_gen.load_schema()`；
`Schema file not found` 类异常 → 打印缺失路径 + 「制品缺件：按 install.md §3A
注记从 codeload tarball 补齐 schemas/，或升级 ≥ v0.1.2」+ exit 1。
与 status 同一校验口径，消除 new/status 校验不对称。

### D4 — 日志卫生（A5/A6）

- 用户配置 loader："顶层不是对象"分支 `logger.error` → `logger.debug`
  （消息保留现场路径）。
- `core/proc_utils.py` `kill_process_group`（全库 `os.getpgid` 唯一调用点 :274）：
  `hasattr(os, "getpgid")` 平台守卫（win32 跳过取组/杀组链）——v2 dev-server 停止链
  （killpg 经 proc_utils）等消费方随之覆盖；launch 处经 pal.spawn_detached，无 getpgid。
- dashboard `core/dashboard/server.py` `DashboardHandler`（stdlib
  `BaseHTTPRequestHandler` 子类 :196）：覆写/包装 `handle_one_request`，
  `except ConnectionResetError`（及 `ConnectionAbortedError`/`BrokenPipeError`）→
  `logger.debug` 单行留痕，不再全栈 traceback（SSE 流路径 sse_routes.py 已有同族
  捕获，本条覆盖 keep-alive/静态等其余路径，两层口径一致均为 debug 单行）。
- docstring r-string 化：`grep -rn '"""' | 含 \d \s 等转义` 机械批改 +
  编译复核零警告——宿主仅 Python 3.10（非法转义在 3.10 编译期发
  DeprecationWarning，SyntaxWarning 口径空转）：宿主用
  `python3 -W error::DeprecationWarning -m compileall core bin`，≥3.12 解释器
  （如过机 Guest 3.13）用 `-W error::SyntaxWarning`
  （只动 docstring/字符串字面量，不改语义；tests/ 已有 characterization 可复核）。

### D5 — install_unit env 注入与服务环境自检（A7）

- `install_unit(root, env: dict | None = None)`：env 非空时经 `_nssm_set`
  写 `AppEnvironment <k>=<v>`？——否，NSSM 2.24 的环境注入参数是
  `AppEnvironmentExtra`（REG_MULTI_SZ）。**直接 Set-ItemProperty 写注册表**
  （`HKLM:\SYSTEM\CurrentControlSet\Services\<svc>\Parameters`，
  -Type MultiString，元素 = "K=V" 列表）——绕开 nssm set 多参数引号坑
  （与手册 §8 B3 口径一致）；或逐元素 `nssm set <svc> AppEnvironmentExtra <k>=<v>`
  单参数循环（单参数无引号歧义）。决策：**注册表直写**（原子、元素边界确定），
  写后提示 restart。写入 MUST 为 **read-modify-write 合并语义**：先读现值，同键
  K=V 覆盖、异键保留，整体回写——真实部署面已有 install.md §8 手工
  `Set-ItemProperty -Name AppEnvironmentExtra` 落的服务 PATH 最小集/DSH_HOME 条目，
  整值替换会将其清除，恰好复发本 SPEC 要治的服务侧 claude 解析失败。
- 自检：幂等重跑（already=True 路径）与 install 完成时，以
  `服务视角 PATH`（AppEnvironmentExtra 里的 PATH 或系统 PATH）解析
  claude/git/python；任一解析失败 → 返回 JSON 增 `env_defect: [明细]` 字段
  （ok 仍 True——安装本身成功，缺陷是环境预警面）。

### D6 — 验证与过机声明

- Linux 全量 0 failed 0 新增豁免（Linux 零变化硬约束；D1 替换仅 win32 生效，
  Linux SpawnSpec 逐位不变，快照测试零触碰）。
- 纯逻辑层新增：解析 helper（which mock）、infra-deterministic 分类
  （FileNotFoundError(2) 不进重试）、schema 前置（缺 schemas/ 时 new exit 1
  不落盘）、env 注入注册表形态（fake registry writer）、日志降级断言。
- **过机复验（必做，不豁免）**：dockur win-test 通道复验 D1/D2/D5——
  ①缺 claude PATH 的服务视角派发一跳终态（不再三连烧）；②which→.cmd spawn
  真链路；③install_unit env= 注入后服务内环境可见 + env_defect 预警。
  收口记录进 windows-native-support 清单执行记录列。

## 交付清单（精确文件面）

- `core/agent_runner/harness/claude_adapter.py`（D1）
- `core/agent_runner/harness/__init__.py`（D1 预检复用）
- `core/agent_runner/` dispatch/归因层（D2，具体文件以实现轮读码为准）
- `bin/fenix_spec.py` + `core/spec_gen.py`（D3）
- 用户配置 loader（A5，实现轮定位）+ `core/proc_utils.py`（getpgid 守卫）+
  `core/dashboard/server.py`（D4）+ 全库 docstring（D4 机械批改）
- `core/platform/win32.py`（D5）
- `tests/test_platform_pal.py` 等（D6 纯逻辑覆盖）
