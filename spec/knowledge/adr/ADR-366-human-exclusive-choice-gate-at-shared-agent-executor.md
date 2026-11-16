# ADR-366：人类专属裁决的执行边界门收敛在 agent 通道共用执行机器

date: 2026-11-16
status: accepted

## Context

人类拍板专属的裁决选项（abandon / force_advance / freeze_stop_loss / grant_env_exemption / raise_budget / revise_reproposal / skip_review_gate）有单源排除集，但越界复核最初只挂在升级链调用方。Administrator 的直派通道与自动执行通道共用同一执行机器、不经链复核，已实际越界执行过人类专属动作（grant_env_exemption 写入豁免并触发仲裁升级，同类先例不止一次）。若把边界门放在动作执行器（execute_adjudication_choice）一层，会同时拦掉人工 Dashboard 通道——「人类专属」退化为「谁都不可执行」，与排除集语义直接冲突。

## Decision

人类专属拍板面的执行边界下沉到三条 agent 驱动通道共用的执行机器入口（execute_choice_for_disposition）：解析出 choice_id 后、调用动作执行器前统一复核排除集，命中即拒绝执行（ok=false + skipped=true + error 含「人类拍板面专属」，与链路径同一文案前缀保证同 grep 可检索）。人工 Dashboard alert-resolve 通道直接调用动作执行器，放行语义永久保留。拒绝后信号不静默收口：disposition 记 handoff_reason、信号保持 pending，交既有升级链/Arbiter 接管。升级链自身的越界复核（handoff 转 Arbiter、不计失败）保持先行，执行机器守卫为第二层设防。

## Consequences

后续任何新增 agent 驱动执行入口天然被覆盖（配合既有单执行机器裁定），不存在「新通道漏复核」面；未来若要把某人类专属 choice 开放给 agent 执行，必须显式从排除集移除并补测试，旁路绕过被门拒绝。代价：链路径存在两道复核（链复核先行 + 执行机器兜底）；执行失败消费侧须识别 skipped 拒绝形态并留 handoff 痕迹，不得按普通失败重试或回写终态。
