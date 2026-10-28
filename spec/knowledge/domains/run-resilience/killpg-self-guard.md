# 进程清场击杀自保护守卫

<!-- knowledge: capability=killpg-self-guard rev=1
     sources=spec/archive/2026-10-28-add-killpg-self-guard -->

core 产品代码的全部进程组清场击杀（`os.killpg` 发送 SIGTERM/SIGKILL）经统一守卫助手
`core/proc_utils.py` 的 `guard_killpg` 执行，防止清场动作命中调用者自身所在进程组，
把宿主进程或整套测试套件团灭。

## 规则

- core 下清场击杀语义的裸 `os.killpg` 调用零存在：所有清场点只经 `guard_killpg`
  发信号，grep 断言测试钉死（探活调用 `killpg(_, 0)` 在显式豁免清单内，不受守卫
  约束，逻辑也不改动）。新增清场点必须走守卫，禁止绕过。
- 守卫在信号发出前做两项校验，任一命中即拒绝发出：
  - 目标 pgid 不得等于调用者自身所在进程组（`os.getpgid(0)`）；
  - 目标 pgid 必须为正值。`killpg(0)` 经 `kill(-pgid)` 折算等价于向调用者自身组
    广播（`kill(0)`），数值上 `0 != os.getpgid(0)` 挡不住，须单独拒绝；负值 pgid
    折算为对任意 pid 的误投递（如 `killpg(-1)` ≡ `kill(1)`）。
- 拒绝时的行为：不发信号，记 WARNING 日志（含调用点标识 `caller` 与目标 pgid），
  按「组已不存在」（ProcessLookupError/OSError）语义静默返回 False。调用方对
  False 一律按组不存在静默收尾——不得抛异常改变调用方控制流，也不得回退触发单
  pid `os.kill` 降级（`os.kill(0)` 同样是自身组广播，替身怪值 pid 不得经由降级
  流入 `os.kill`）。
- 守卫兼容两种入参形态，调用点按形态显式传 `resolve` 参数：
  - 解析型（`resolve=True`）：入参为组内成员 pid，守卫内部先 `os.getpgid` 解析
    pgid（如 `core/regression.py` 的清场函数）；
  - 组长直传型（`resolve=False`）：入参为独立成组组长 pid，直接作 pgid（如
    `core/agent_runner/liveness.py`、`core/agent_runner/maintenance_runs.py`）。
  两种形态的拒绝/放行判定同一口径（自身组比对 + 非正值拒绝），不因形态漂移；
  解析失败的既有静默语义逐位保持。
- 各清场点的 SIGTERM → 宽限等待 → SIGKILL 补刀序列、探活（`killpg(_, 0)`）与
  补刀判断逻辑逐位保持，仅信号发出的最后一跳收口到守卫；对经
  `start_new_session=True` 独立成组的真实子进程树触发清场时，序列照常执行、
  进程组全灭、不产生 WARNING。
- 测试替身 proc 的 pid 怪值须用正值越界 pid（超出 Linux 默认 pid_max，如
  `2**22`）表达不可达：直传型清场点语境下 `-1` 折算为 `kill(1)` 误投递，`0`
  等价自身组广播，均禁用。替身修复与守卫互为冗余防御。

## 关键行为

- 守卫永远开启，无配置开关；业务上不存在「合法清理自身组」场景，误拦面为零。
- 覆盖面为全 core 清场点：全量回归（`regression.py`）、agent_runner（`liveness.py`
  / `maintenance_runs.py`）、verify_engine（`cli_runner.py`）、dev server、裁决叙述、
  知识回填、worktree dist 冲突清理、OCR 状态、架构路由、会话管理、hook 引擎、
  serving registry、dashboard 回归路由等。

## 溯源

- 2026-10-28 add-killpg-self-guard（spec/archive/2026-10-28-add-killpg-self-guard） —
  新增本页：`guard_killpg` 统一守卫落地、全 core 清场点收口、非正 pgid 单独拒绝、
  拒绝时禁单 pid 降级、替身怪值改正值越界 pid。
