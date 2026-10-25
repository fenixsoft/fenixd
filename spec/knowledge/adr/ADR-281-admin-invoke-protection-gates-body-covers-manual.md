# ADR-281：admin 唤起保护闸收本体、人工与自动同政策

date: 2026-10-26
status: accepted

## Context

admin 车道不经 pm_engine 派发队列，Administrator 唤起点是唯一派发收口；provider 瞬断冻结态或夜间静默窗期内唤起 admin run 必死，死后还留下 fail-closed 升级滞留。共用唤起入口的闸门落点在仓库内已有两条方向相反的先例：alert-noise-governance 裁定抑制类判定必须留在各调用点、不得收进唤起入口本体（防误伤人工显式触发通道）；sigterm-source-tracking-cooldown 则把 spec 级信号死法冷却闸放在本体。后续任何需要在唤起入口加闸的 SPEC 都会撞上这对矛盾先例，落点与「人工通道是否豁免」无从援引统一裁定。

## Decision

按闸门目的二分落点：保护类避让闸（provider 瞬断冻结态、夜间静默窗）收在唤起入口本体，与信号死法冷却同位，自动检测与人工显式触发同政策——断窗/冻结期内人工唤起同样必死，保护闸没有豁免人工的理由；抑制类判定（夹具项目抑制）维持留调用点、人工不受限。保护闸命中的跳过属非失败路径：MUST NOT 增 retry_count、MUST NOT 落升级告警，仅 INFO 留痕原因，留待下一轮盘点重试。窗配置复用 code-fix 车道静默窗的同一配置键与解析，不引入第二份窗配置。

## Consequences

断窗拉长时 admin 处置响应顺延，依赖升级通道 fail-closed 兜底；预计跨窗顺延会推迟部分本可赶在窗前完成的短批，以极窄区间的延迟损失换整批免杀重跑。后续在唤起入口加闸的 SPEC 按保护/抑制二分选落点：不得援引 alert-noise-governance 把保护闸散布到调用点，也不得把抑制判定收拢进本体；闸门语义写清「保护 run 生命」还是「抑制噪音召唤」即为分界。
