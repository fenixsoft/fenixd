# proposal — add-codefix-conn-error-cooldown

## Why

code-fix 车道（夜间批量修复 code-review 台账的维护车道）完全绕过 provider 切换/耐受机制：maintenance_runs.run_code_fix 只取链首 assignment[0] 直调 _run_claude（maintenance_runs.py:2386-2455），不经 _execute_agent_inner 的链迭代与 switch 冷却；批次失败收尾按 consumed 自驱动零延迟重派（code_fix.py:3847→3741→2992→2544），唯一闸门是 _in_flight 单飞标志，无任何时间维度判定。

实测后果：2026-09-28 起连续 4 天，上游网关每日 UTC 20:31 前后出现约 100 秒连接性窗口（真实死因是「API Error: Can't reach the API server (ENOTFOUND)」连接故障，非拒模型——unrecognized_model stderr 行是 glm/deepseek 链每 run 定噪，provider_circuit.py:101-103 自证），每窗恰好烧毁 2 个 run：一个带真实工作量的在跑批次（10-01 一批 368 轮 / 28 分钟 / $16.38）加一个 0 轮重派，失败后 3.35 秒即撞回同一窗口。admin_monitor 的 daemon_errors 指纹监视 09-29 已给出正确诊断（日志行 36131），但 09-30 起被「已知指纹 30 分钟冷却」静默（日志行 38233/38237），跨日复发信号被既有机制压掉。

## What Changes

- 失败分类：runner 异常挂载层新增「连接类 api_error」布尔（terminal_reason=api_error + exit_code!=0 + result_text 命中扩充后的连接类词表），经 CodeFixResult 透传进 code-fix 车道；词表补「Can't reach the API server」「ENOTFOUND」形态（现有词表实测对本死因文本漏判）。
- 车道冷却：code-fix 失败收尾命中分类时写持久化冷却态（fix-progress.json 新增 switch_cooldown_until 字段），checkpoint 投递入口守卫「同链下一批不早于冷却到期时刻」；冷却常数复用 PROVIDER_SWITCH_COOLDOWN_SECONDS，配置键 admin.code_review_fix.switch_cooldown_seconds 可覆盖。
- 告警：冷却触发/解除经 AdminStore 写 SIGNAL 告警（新 signal_type）；daemon_errors 指纹记账增加「跨日同刻复发」升级维度，不受已知指纹 30 分钟冷却压制。

## Non-Goals

- 不给 code-fix 车道引入模型链迭代/快切（车道当前单 provider，链语义不可平移）。
- 不改 spec/impl 车道既有切换与冷却行为。
- 不处理 administrator/self-review/evolution 等兄弟维护车道的同型盲点（留待后续条目）。
- 不动 evo-code-fix-api-timeout-salvage 的现场抢救语义（两者仅共享 api_timeout 布尔，分工见 design）。