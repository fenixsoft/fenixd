# killpg-self-guard delta：进程清场击杀自保护守卫

## ADDED Requirements

### Requirement: 清场击杀不得命中调用者自身进程组

产品代码所有进程清场击杀路径（`os.killpg` 发送 SIGTERM/SIGKILL）SHALL 经统一守卫助手执行；守卫 SHALL 在信号发出前校验目标进程组不等于调用者自身所在进程组（`os.getpgid(0)`）、且目标 pgid SHALL 为正值（`pgid <= 0` 经 `kill(-pgid)` 折算等价调用者自身组广播 `kill(0)` 或对任意 pid 误投递，SHALL 同样拒绝）；命中即拒绝发出、记 WARNING 告警日志（含调用点标识与目标 pgid），并按既有「组已不存在（ProcessLookupError/OSError）」语义静默返回——MUST NOT 抛异常改变调用方控制流，MUST NOT 发出信号，MUST NOT 回退触发单 pid `os.kill` 降级。

- 守卫助手 SHALL 兼容两种入参形态：解析型（传组内成员 pid，先 `os.getpgid` 解析）与组长直传型（传独立成组组长 pid 直接作 pgid）；解析失败的既有静默语义逐位不变。
- 各清场点的 SIGTERM → 宽限等待 → SIGKILL 补刀序列、探活（`killpg(_, 0)`）与补刀判断逻辑 MUST 逐位保持，仅信号发出的最后一跳收口到守卫。
- 存量测试替身的 pid 怪值（`tests/test_codefix_digest_metrics.py` 的 `self.pid = 0`）SHALL 改为不可达 pid：该替身流入组长直传型清场点，不可达性 MUST 以正值越界 pid（超出 Linux 默认 pid_max，如 `2**22`）达成，MUST NOT 照抄 `test_knowledge_backfill.py` 先例的 `-1`（其不可达性来自 resolve 型 `os.getpgid(-1)` 抛错，直传型语境下 `-1` 折算为 `kill(1)` 误投递）——替身修复与守卫互为冗余防御。
- core 下 SHALL 留有 grep 断言测试：清场击杀语义的裸 `os.killpg` 调用 MUST 零存在（探活调用点显式豁免清单除外），防未来新增清场点绕过守卫。

#### Scenario: 替身 pid=0 不再团灭宿主

- **WHEN** 测试替身 proc 的 `pid=0` 流入任一收口后的清场函数并走到击杀跳
- **THEN** 宿主（pytest 自身）所在进程组 MUST NOT 收到任何信号，清场函数按组不存在静默返回且留 WARNING 日志

#### Scenario: 正常独立组清场行为不变

- **WHEN** 清场函数面对经 `start_new_session=True` 独立成组的真实子进程树（组长存活）触发超时清场
- **THEN** SIGTERM → 宽限 → SIGKILL 序列对该组执行结果与守卫引入前逐位一致，进程组全灭且无 WARNING

#### Scenario: 守卫拒绝留告警

- **WHEN** 任一清场点的目标 pgid 解析结果等于调用者自身进程组
- **THEN** 信号 MUST NOT 发出，WARNING 日志 MUST 包含调用点标识与目标 pgid，调用方控制流与「组已不存在」分支逐位一致

#### Scenario: 两种入参形态语义一致

- **WHEN** 解析型（成员 pid）与组长直传型（组长 pid）两个清场点分别以相同 pgid 目标触发守卫校验
- **THEN** 两者的拒绝/放行判定 MUST 一致（同一自身组比对口径），不因入参形态不同而漂移

#### Scenario: 直传型非正 pgid 被拒绝

- **WHEN** 组长直传型清场点收到替身怪值 `pid=0` 或负值 pid 并走到收口后的击杀跳
- **THEN** 守卫 SHALL 拒绝发出（`killpg(0)` 经 `kill(-pgid)` 折算等价调用者自身组广播，数值比对 `!= os.getpgid(0)` 挡不住，MUST 单独按非正 pgid 拒绝）、留 WARNING、按组不存在静默返回，宿主进程组 MUST NOT 收到信号
