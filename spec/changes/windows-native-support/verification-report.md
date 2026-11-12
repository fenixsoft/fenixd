# 验证报告：windows-native-support

> ⚠️ 本报告由框架于 2026-11-12T16:16:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-12T16:05:08.585015+00:00+run-result@mtime1794500159432866580

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 10/11 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

11 场景中 10 通过、1 失败（product-bug）。唯一失败为 linux-zero-change-full-regression：全量失败足迹越界且越界文件单跑复现真失败，判疑似本次引入；其余 Windows 平台化落点（PAL 六组对等、终止地基、死法分类、端口语义、安装链、dockur 通道、双平台 CI、Linux 依赖隔离）全部通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 14.67M |
| 本链增量 Token（输出） | 0.21M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code + output_match

- 关联场景：linux-zero-change-full-regression
- 描述：Linux 零变化硬约束验收失败：有界全量失败足迹越出 tasks.md 7.2 存量基线簇 8 文件，越界文件 tests/test_task_artifact_ownership.py 单跑复核后仍复现真失败，按冻结协议判为疑似本次引入（非顺序污染足迹漂移）。
- 根因：越界测试文件单跑复现真失败（非套件顺序污染的足迹漂移），根因待实现侧定位；同场景其余断言（守卫双测试 102 passed/5 skipped、pal 门面行为、linux.py 纯新增、__init__.py/pytest.ini/release.yml 不动）均通过。
- 证据（场景 linux-zero-change-full-regression 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": "步骤3 full-suite(as=full-suite)", "expected": 0, "actual": 1}, {"type": "output_match", "selector": "FULLSUITE-CLASSIFY", "expected": "OK FULLSUITE-CLASSIFY", "actual": "FAIL FULLSUITE-CLASSIFY :: 越界文件单跑复现真失败（疑似本次引入）: tests/test_task_artifact_ownership.py"}]
  - screenshots: []
  - first_failed_step: 步骤3 as=full-suite：有界全量失败足迹越界（存量基线簇 8 文件外出现 tests/test_task_artifact_ownership.py），单跑复核复现真失败，冻结协议判疑似本次引入，退出码 1


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| win32-backend-parity-and-deliverables | win32 全后端交付物与六组接口对等：requirements-win32.txt / install.ps1 / tests/integration/windows/{README.md,run_integration.ps1,g1_full_parity_checklist.md} / .github/workflows/windows-integration.yml 落位；win32.py 与 linux.py 对 api.py 六组 Protocol（ProcessLifecycle/ProcessIntelligence/FileLocking/HostingSeam+HostingProvider/EnvironmentUserFs/TestInfra，core/platform/api.py:84-226）同名同签名（AST 对账，FunctionDef+AsyncFunctionDef 二元组收集、Protocol 方法剥 self——judge 修复①口径）、零 raise NotImplementedError 残留、IS_WINDOWS 谓词双侧在位、F 组 pytest_timeout_method 恒 "thread"；__init__.py sys.platform 单点分发不变；Windows 依赖（psutil/pywin32）仅进 requirements-win32.txt，core/ 非 platform 区零 win 依赖 import，仓库不引入打包体系（无 pyproject.toml/setup.py）。出处：specs/windows-native-support/spec.md Requirement「win32 后端实现 PAL 六组接口」两 Scenario、tasks.md §2、design.md 现场锚点与决策 1 | pass | 0/7 | - |
| win32-contract-tests-linux-runnable | win32 后端平台无关行为契约在 Linux 可跑：tests/test_platform_pal.py 全绿（实测 99 passed, 5 skipped）；win32 语义命名测试（测试名或所属类名含 win32/windows，AST 口径）≥6 个覆盖六组（实测 18 个）；Windows-only 用例带 skipif(sys.platform != "win32") 门；探针直接 import core.platform.win32（Linux 可导入——模块级纯 stdlib、懒加载设计）。出处：tasks.md 7.1、knowledge 页 platform-abstraction「win32 契约测试两层形制」、tests/test_platform_pal.py:948/1041 | pass | 0/6 | - |
| linux-face-win-dependency-isolation | Linux 依赖面零引入运行时实证：以 sys.meta_path 拦截钩子封禁 psutil/portalocker/pywin32 族模块后，core.platform 及全部 SPEC 触达消费面（proc_utils/fs_utils/systemd_hosting/event_bus/agent_runner liveness/runner/provider_circuit/maintenance_runs/claude_adapter/verify_engine cli_runner/dashboard http_server/server/fenixd 顶层）import 全部成功；pal.pytest_timeout_method() 仍为 signal（Linux 形态未被带偏）。出处：spec.md Scenario「Windows 依赖不进主依赖面」、tasks.md 5.1、design.md 决策 1 依赖面规则 | pass | 0/5 | - |
| win32-termination-foundation-anchors | W8 A 组 + W9 终止地基锚点：win32.py 含 Job Object 锚（KILL_ON_JOB_CLOSE/AssignProcessToJobObject 族）与 Toolhelp 快照兜底锚、分层终止面（GenerateConsoleCtrlEvent+CTRL_BREAK，design.md 决策 2 spike 结论三层有效）、CREATE_NEW_PROCESS_GROUP、TERM_GRACE_SECONDS 宽限常量；弃用 taskkill 断言（零回潮）；终止面六函数（stdin_eof/terminate_graceful/kill_tree/kill_group_alive/bind_to_parent/spawn_detached_async）双侧 __all__ 导出；core/proc_utils.py + agent_runner/runner.py + harness/claude_adapter.py 分层终止接线（pal 终止面调用 ≥1 处/文件）；Linux 对称位 stdin_eof 恒 False（签名兼容位零行为变化）。出处：spec.md Requirement「优雅终止分层协议」、tasks.md 2.1/3.1、design.md 决策 1/2、knowledge 页 platform-abstraction「win32 后端要点」 | pass | 0/5 | - |
| death-kind-orphan-platformization | W14 死法分类与孤儿判据平台化落点：pal.exit_code_signal_name 单源行为闭集（Linux 侧 -9→SIGKILL/143→SIGTERM/129..159 128+N 族/非信号形态恒 None、0xC000013A 在 Linux 后端恒 None——实测锚）；win32.py Windows 闭集两态锚（STATUS_CONTROL_C_EXIT/0xC000013A）；runner.AgentRunner._signal_kill_label 薄委托保留 [signal-kill: NAME/CODE 格式（143→[signal-kill: SIGTERM/143] 实测）；provider_circuit.py Exit 143/-9 信号死法判据职能锚（SIGNAL_KILL_COOLDOWN_AFTER/SECONDS/record_signal_kill——judge 修复③口径：落点是判据职能非 pal 标记字面）；maintenance_runs.py [signal-kill: 标签消费 + pal 引用；liveness.py death_kind 收场 + pal 引用；dashboard/server.py pal.orphaned_process() 孤儿启动判据（Linux 语义 os.getppid()==1 逐位保留在 linux.py）；event_bus 消费面按实现期 grep 零落点不设判据。出处：spec.md Requirement「死法分类与孤儿判据平台化」两 Scenario、tasks.md 3.2、design.md 决策 6 | pass | 0/6 | - |
| bin-posix-face-and-supervisor | bin/ 6 文件进程模型不变量与 POSIX 面收敛（fenixd_supervisor/dsh_acceptance/fenix_verify_contract/migrate_to_systemd/run_full_suite/test_for）：全库（core/+bin/）零 os.fork、零 multiprocessing；bin/ 6 文件每文件至少一种平台收敛形态（pal./pal.IS_WINDOWS/os.name=='nt'/sys.platform=='win32' 谓词三形态——judge 修复④词表口径）；SIGBREAK 引用仅限平台守卫 If 区间内（server.py + fenixd_supervisor.py 两处，AST If 守卫区间豁免口径）；信号处理器注册面全库仅 core/dashboard/server.py 与 bin/fenixd_supervisor.py（signal.signal/add_signal_handler 零漂移）。出处：spec.md Requirement「bin/ 进程模型与 POSIX 面收敛」、tasks.md 3.3、knowledge 页 platform-abstraction「进程模型不变量/信号注册面」 | pass | 0/5 | - |
| port-rebind-linux-equivalence | W13 端口语义 Linux 侧零变化：core/dashboard/http_server.py allow_reuse_address = not pal.IS_WINDOWS 表达式在位（Linux 恒 True——SO_REUSEADDR 既有语义）+ server_bind 覆写 SO_EXCLUSIVEADDRUSE 仅 Windows 分支（pal.IS_WINDOWS 守卫）；行为级：DashboardHTTPServer.allow_reuse_address is True（Linux 实例形态）+ SO_REUSEADDR socket 释放后立即重绑同端口成功（无 TIME_WAIT 复用失败/静默抢占形态）；server.py 占用 errno 闭集 Linux 三值 (98,48,56) 在前 + Windows 三值 10013/10048/10054 增补（design.md spike 结论）。出处：spec.md Requirement「端口语义重验」Scenario「重启无端口残留失败」、tasks.md 4.1、design.md「W13 SO_REUSEADDR」spike 结论 | pass | 0/5 | - |
| install-chain-deliverables | W10 安装链 PowerShell 化：install.ps1 消费 requirements-win32.txt 装依赖、PATH 基线 win32 版（[Environment]::SetEnvironmentVariable User 域）、软链需求 symlink→junction→copy 降级链（New-Item -ItemType SymbolicLink/Junction/Copy-Item 三态在位，实测 L118-151）、幂等可重入（Test-Path/-Force + 「可重复执行（幂等）」docstring）；requirements-win32.txt 形态：psutil/pywin32/PyYAML/httpx/jsonschema 生效行在位、portalocker 保持注释备选态（C 组 msvcrt.locking 主选不纳入）；requirements*.txt 全仓唯一（Linux 依赖面零新增清单）。出处：spec.md Requirement「安装链 PowerShell 化」Scenario「无开发者模式特权时降级成功」、tasks.md 5.1/5.2、design.md 决策 1/3 | pass | 0/6 | - |
| dockur-channel-and-g1-infra | W11 dockur/windows 集成通道交付（分面判据——judge 修复②口径：README 承载宿主侧锚、ps1 承载 Guest 侧锚）：tests/integration/windows/ 三件落位——README.md 宿主侧通道锚（8006 viewer/8889 RDP、/oem install.bat 装机、/shared→Z: 传码、USERNAME/PASSWORD 凭据约定、连续 ≥3 次失败环境止损纪律）；run_integration.ps1 Guest 侧锚（Z: 盘、install.ps1 依赖链、G1 清单逐项驱动 PASS/FAIL 汇总、任一 FAIL 退出码非零）；g1_full_parity_checklist.md G1-01..G1-25 全 25 条在位 + 六组语义锚覆盖 ≥6 组（Job Object/CTRL_BREAK/psutil/msvcrt 锁/junction 降级/NSSM/pytest/原子写）。出处：spec.md Requirement「dockur/windows 集成测试通道」Scenario「一键过机验收」、tasks.md 6.1 | pass | 0/5 | - |
| windows-ci-workflow-release-intact | W12 双平台 CI：.github/workflows/windows-integration.yml 合法 YAML（PyYAML safe_load）、jobs.guest-parity 在位、runs-on 指定 dockur 自建 runner 三标 [self-hosted, Windows, dockur]、push/workflow_dispatch 触发、引用 tests/integration/windows/run_integration.ps1 过机通道、timeout-minutes 有界；release.yml 相对 merge-base(main,HEAD) 逐字节不动（现有发布流水线零影响）。出处：spec.md Requirement「双平台 CI」Scenario「双绿合入」、tasks.md 6.2 | pass | 0/5 | - |
| linux-zero-change-full-regression | Linux 零变化验收（硬约束 1，按 tasks.md 7.2 行内替代验收注解出题：以 bin/run_full_suite.py 有界全量 + main 基线失败集合归类替代「pytest tests/ -q 0 failed」字面——47 项存量失败全部落 knowledge/archive/preflight 系 8 文件、与本 SPEC 改动测试文件零交集，证据 .fenix/verify-evidence/windows-native-support/72-baseline-comparison.md）：①守卫双测试 python3 -m pytest tests/test_platform_guard.py tests/test_platform_pal.py -q 全绿（实测锚 102 passed, 5 skipped，零豁免漂移）；②pal 门面行为回归（timeout_method=signal/退出码闭集/stdin_eof False/IS_WINDOWS False/systemctl_available/SIG 常量——Linux 语义逐位不变的行为级实证）；③linux.py 相对 merge-base(main,HEAD) 零删除/修改行（W8 四接口纯新增签名兼容位）；④core/platform/__init__.py 与 pytest.ini（timeout_method=signal）与 .github/workflows/release.yml 相对 merge-base 逐字节不动；⑤有界全量 run_full_suite.py --json 失败文件集合 ⊆ 存量基线簇 8 文件（越界即疑本次引入）。出处：spec.md Requirement「Linux 零变化验收（硬约束 1）」Scenario「全量绿」、tasks.md 7.2（2026-11-12 admin 修订：⑤静态白名单一次判死升级为越界文件逐个单跑复核自证归类——单跑全绿判顺序污染足迹漂移非本次引入，单跑复现才判疑似本次引入；冻结期 8 文件白名单无法容纳套件失败足迹漂移，judge 两轮人工复核同法实证后固化） | failed（已修正） | 2/8 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

