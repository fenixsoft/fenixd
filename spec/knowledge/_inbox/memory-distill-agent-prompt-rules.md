# memory 存量蒸馏：agent 提示词/测试编写设计规则

## 背景

auto-memory 存量中关于「如何写 agent 提示词、如何写测试」的设计级教训——多次烧钱
事故换来的规则，多数从未走 SPEC（提示词与测试为原地修复）。适合折叠进
agent-runtime / test-engineering 域。

## 结论（当前事实）

### 提示词编写

- 提示词里任何「≤N 字」都会被模型当**硬截断指令**字面执行（title 被截成
  description 前 40 字、180/181 条命中的实证）——表达「简洁」用语义约束，
  不用数字上限。
- claude -p 非交互模式下 **turn 结束=主进程退出，async 子代理结果永不回收**；
  「等待通知/等待批次完成」在非交互模式不存在。Task 子代理必须同步回收
  （一轮内拿结果）或走分片直写+读侧聚合；code-review 车道曾因此两晚烧 $39 零产物。
- 提示词路线 **3+ 次失败=架构问题，勿再改提示词**（护栏须框架侧：心跳/时长判据/
  机械拦截）。同族教训：辅助工具死掉时 agent 会归因瞬态失败无限重试，提示词的
  「降级继续」条款降不住不死心，护栏必须框架侧。
- 新增「run 产出结果文件 → 独立消费函数」的门禁型 agent，必须**同时定义消费触发者**
  （谁在何时调用）；防重派锚点必须落在**启动 run 之前**落盘（spec-review 车道
  7 次评审全 repaired 却来回重派的根因）。
- daemon 一次性派发下后台 Bash 完成通知**从不送达**——implementer 按提示词
  「等待通知」收工=启动即忘→partial 占位→重派循环。涉及后台任务须轮询文件产物
  而非等通知。
- prompt「分批落盘」约束对快模型无效（deepseek-v4-flash 仍一次性写全量）——
  需要分批就机械化（PreToolUse hook），勿依赖模型自律。
- 全局开关常开下用户级配置敏感测试用 `patch("core.config.USER_CONFIG_DIR")` +
  `patch("core.dashboard.data.USER_CONFIG_PATH")` 双隔离（仓内既定模式）。
- 改 prompt 文件先 merge main（契约段=动态段 prompt_builder.py + 模板 agents/*.md，
  旧内置 f-string 补丁必撞 merge 冲突）；实现 agent 只在非契约段追加。

### 测试编写

- 测试内替换**进程级全局**对象（如 `subprocess.Popen`）必须 try/finally 复原——
  复原裸写在用例尾部，SIGALRM（10s 单用例硬门）在复原前打断即全局泄漏，其后
  所有子进程用例连坐超时（一场 85+ 用例全 F、回归撞满 1800s 实证）。普通 pytest
  类**没有 addCleanup**（只有 unittest 有）。
- 测试假 spawn 按 `cmd[0]` 分发（真子进程直通、假命令返回 fake），勿按序号或
  全局一刀切。
- 夹具指向 `spec/changes/<SPEC>` 会在 SPEC 归档时批量失效成为 judge 噪音源——
  夹具 MUST 指向 `spec/archive/`（12 条存量已清零并固化做法）。
- pytest basetemp 落仓库内两坑：git 上溯发现主树（conftest 钉 `GIT_CEILING` 切断）
  + 并发 pytest 会话互删工作区产假失败——取证跑 pytest 须显式独立 `--basetemp`。
- watchdog/常驻线程类测试必须收割线程（tests/conftest autouse 收割已落地）：
  `monkeypatch.setenv("CLAUDE_PID", ...)` 会起 watchdog 线程盯 pytest 自身 pid，
  泄漏后在负载峰值窗口集体误判死亡并 `os.kill(os.getpid(), SIGTERM)` 自杀
  （89 泄漏线程、非确定性 1/3 复发率实证）。
- sed 勾选 tasks.md 时 replacement 端 `\^` 误转义产生 `^-` 前缀→任务清单解析为空；
  agent 自检 grep 计数=0 时必须停下核实而不是强行提交收工。
- 单测通过≠生产生效：daemon 进程代码改动须重启才生效（在飞 run 期间不重启，
  等空窗）；「修复无效」先核对 `.fenix/daemon_started` 与修复提交时间。

### worktree 隔离与路径锚定

- **注入上下文里的任何绝对路径都可能成为模型的落盘锚点**：skill 注入文本首行的
  主树绝对路径曾使 implementer 全程写主树（39 次写盘 0 次 worktree，隔离失效）。
  防线已落地：`.fenix/hooks/block-main-tree-write.py` PreToolUse 拦截
  （白名单=verify-progress，主树 deny+纠偏提示）+ runner 注入
  `FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE` env + implementer prompt 工作目录段。
  排查「agent 写错位置」：/proc cwd（排除 spawn 问题）→ 转录 tool_use file_path
  分布 → 其调用的 skill 注入文本。
- 跨树操作纪律：本会话 cwd 被切进 worktree 后改主树文件+在 worktree 跑验证=
  验证的永远是旧代码（修复「无效」假象）——跨树操作显式 cd 或双树各验。
- 手工改主树文件遇磁盘异动（函数/导入被删）：先判别误伤 vs 并行 worker 重构——
  调用点清零+测试配套删+编译自洽=重构让路，勿回滚。

## 证据

- 源记忆：fenixd-codereview-ledger-hygiene（≤40 字截断段）、
  fenixd-codereview-async-agent-mechanical-failure、fenixd-specreview-lane-gaps、
  fenixd-background-notification-one-shot-dead、fenixd-planner-family（分批落盘段）、
  fenixd-codefix-regression-selfpoison-loop-1008（try/finally 段）、
  fenixd-test-isolation-popen-hijack-and-head-scan、fenixd-test-fixture-archive-blindspot、
  fenixd-pytest-basetemp-inside-repo-git-discovery、fenixd-codefix-regression-sigkill-loop-1007
  （watchdog 泄漏段）、fenixd-sed-caret-tasksmd-blank-tasklist、fenixd-skill-basepath-anchors-main-tree、
  fenixd-implementer-selfkill-ps-grep-pytest、fenixd-manual-fix-auth-whole-chain
  （双隔离段）、fenixd-prompt-files-merge-conflict-rehome、
  fenixd-parallel-worker-same-file-discrimination。
- 现行锚点（2026-11-04 复核）：`.fenix/hooks/block-main-tree-write.py` 存在；
  `agents/code-review.md:34` ocr 反回归注记现行；tests/conftest 收割 fixture 现行。
