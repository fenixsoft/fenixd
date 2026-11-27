# 设计：车道探针稳态降噪与告警生命周期对齐

## 关键决策

- D1 稳态记忆放探针体内：lane_preflight 维护上次判定结论与进入稳态时刻；结论不变时跳过逐拍 WARNING，改由 3600s 节流心跳携带持续时长发射；结论变化（含首次判定）立即 WARNING。判定返回值（ok/reason）与派发冻结闸消费路径零改动。
  - **边沿判据可比域**：「结论」= `(ok, fallback_verdicts, reasons 归一集)` 三元全同才算同判稳态；任一位漂移（unhealthy 同判但失败形态变化——如 CLI 缺失→凭据缺失叠加、verdict missing↔indeterminable 翻转）即按新边沿即时发射，防止形态漂移被同判静默吞掉。
  - **并发与时基约束**：探针有多消费方（fenixd.py:1342 启动、:1362 周期 tick 直调 + runner 回落冻结闸经 LanePreflightCache），稳态记忆 MUST 进程级单例并锁保护（防并发拍读写撕裂与心跳重复计时），持续时长以 time.monotonic 计（与 LanePreflightCache 同款，防墙钟跳变）。
  - **与 evo-repair-lane-credential-probe-fix 1.2 组合**：试呼裁决（indeterminable→ok/unhealthy 翻转）天然落入「结论变化」→边沿发射，本机制无需感知试呼本体。
- D2 自检消费点复用：fenixd.py _lane_preflight_consume 不再无条件重打（:1290-1294），改为仅在探针侧标记本拍为「边沿/心跳拍」时发射，天然消除双组件同拍双行。标记建议随 LaneHealth 携带（新增带缺省字段，frozen dataclass 兼容既有构造方）或经锁保护的模块级查询口，MUST NOT 用无锁裸模块级布尔。
- D3 告警重武装判据区分稳态与判定变化：人工 handled 后，若下一拍判定仍为同一稳态（同判且 reasons/verdicts 未漂移），不重开新告警（一次性终态登记）；若判定改变（环境形态变化或试呼裁决翻转），按新边沿重新登记。这是对 lane_preflight.py 告警登记段「人工已处理条目不再抑制新告警落地」设计（_lane_env_alert_inflight :371-381）的稳态例外，保留其瞬态场景语义。**闸 MUST 收口在 ensure_lane_env_alert 入口统一生效**——dsh-plugins 实证三次重开均 origin=periodic，但登记调用方共两个（fenixd.py:1295 _lane_preflight_consume 承载 startup/periodic，core/pm_engine/arbiter.py:1972 run infra 失败路径），闸放入口即全覆盖，任一绕过即闸失效。
  - **与 evo-repair-lane-credential-probe-fix 1.3 共存**：1.3 的 >24h 话术翻转走 AdminStore update 定位改写路径（append_if_absent 之外），本闸只抑制「同判稳态下的 append 重开」，MUST NOT 拦截 update 改写——两机制正交可叠加。
- D4（撤销原「提醒豁免」决策）：>24h 提醒生命周期方向由已提交的 evo-repair-lane-credential-probe-fix 1.3 承接（升级话术翻转），本 SPEC 不实现提醒豁免、不改 core/self_review.py——避免同一告警面被两个 SPEC 按相反方向各改一次。
- D5 双 SPEC 同文件协调：本 SPEC 与 evo-repair-lane-credential-probe-fix 均修改 core/agent_runner/lane_preflight.py（本 SPEC：稳态记忆+登记闸；对方：试呼+话术翻转+update 改写）。后落地方 MUST 以对方已落盘语义为基线合入；稳态记忆边沿判据天然覆盖试呼裁决变化，两机制无语义冲突，仅存在文本合并次序问题。

## 风险与对策

- 风险：稳态心跳间隔过长掩盖恢复——对策：恢复（healthy 边沿）始终即时播报，保留并升格既有 _lane_preflight_ever_unhealthy 恢复播报语义（fenixd.py:1319-1325）。
- 风险：边沿判据过窄吞掉形态漂移——对策：D1 可比域含 reasons/verdicts 全集，任一漂移即新边沿；单测覆盖「unhealthy 同判但形态漂移」分支。
- 风险：与在途 credential-fix 的合并次序冲突——对策：D5 协调约定；实现方动手前先核对方是否已落盘 lane_preflight.py。
- 兼容：不改 evo-provider-fallback-dispatch-gate 的「不可判定→拦截+告警」意图，本 SPEC 只接管该形态的观测面；三值判定词表与 fallback_verdicts 消费契约零改动。
