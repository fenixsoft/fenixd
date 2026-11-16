# Design: add-escalation-chain-admin-arbiter

## Context

- 设计真相源：`docs/superpowers/specs/2026-11-03-escalation-chain-admin-arbiter-design.md`（用户 7 定调 + builder check 链语义细则 8 条，2026-11-03 定稿）——本 SPEC 的需求与裁决全部以该文档为准，本文只做工程落点
- 11-02 取证事实：`inconclusive_loop`/`warning_stale_triage` 不在 arbiter 白名单直接落人工；`verify_env_blocked` 走 arbiter 因 provider 链缺失 0.001s 秒败；原始 escalation 无 `admin_run_id`/`trigger` 致 Admin 处置成功后仍滞留人工队列
- 既有机制底座：arbiter 单飞队列与台账五段（`core/pm_engine/arbiter.py`）、Admin 处置包与在飞互斥（`core/admin_monitor.py`，bc3c07e8 家族守卫）、choices 注册表（`core/dashboard/data/adjudication_choices.py`）、`close_escalations_for_run`（`core/admin_store.py:995`）、narrative 让位判定（`core/adjudication_narrative.py:81`）、时间轴联查（`core/dashboard/data/timeline.py:200`）

## Goals / Non-Goals

**Goals**

- 升级边默认入链（Admin→Arbiter→人工），人工队列只显失败上升件，出场即带全链调查
- 双车道配额治理（2 次/签名 + 复位窗）取代 D6 单次纪律
- 全链可观测（时间轴/处置链视图/设置界面）与闭环语义完整（收口+解冻）
- 降级态（kill switch/关闭/失能）与合入前逐字节一致

**Non-Goals**

- 不改各信号既有自愈/重试梯子；不合并 Admin/Arbiter 车道；不改两车道 run 机制（预算封顶/处置包形态/单飞队列上限）
- 不动 Knowledge-Distiller 等硬编码 claude 旁路车道
- 不做跨项目链（链是 per-project daemon 内的）

## Decisions

1. **链派发器独立成模块**（`core/pm_engine/escalation_chain.py`）：事件驱动直派，对齐 arbiter lane 单飞队列形态（同签名 dedup + 复用在飞互斥守卫 + 队列深度上限）；不走 admin_monitor 5 分钟巡检（巡检延迟+backoff 会吃满两级链延迟）。admin_monitor 保留兜底看护，pending 超时升级语义不变、看护对象扩展全链在办件。
2. **配额状态独立 state 文件**（`.fenix/escalation_chain_state.json`，gitignored）：`{signature: {admin_attempts, arbiter_rulings, last_seen, ...}}`——计数是状态不是台账事实，不入 arbiter ledger；签名键复用 `arbiter_failure_signature` 并扩展主体键提取（spec=null 时从 payload 取主体）。主树运行时写入仅 daemon 做，实现分支只交付代码。
3. **Admin 超范围=新结构化产出**：disposition 产出 `handoff: "arbiter"` + `handoff_reason`，不重载 `result=escalate`（现语义「需人工决策」的消费者不破坏）；`agents/administrator.md` 契约段 + `prompt_builder.py` 注入同步（改 prompt 先 merge main）。
4. **预算拍板面**：Arbiter 处置 side-effects 扩展写 spec 预算 override 字段（`impl_run_budget_override` 等，既有字段复用不新增 schema），台账 `action_or_upgrade` 留痕；Admin choices 白名单不含预算/豁免类（受限视野不拍全局政策）。
5. **上升件=链终点专属落盘路径**：`_send_human_escalation_alert` 保留为唯一写入口，新增链上下文参数（链 run_id 族/Admin 尝试摘要/台账回链）；链内成功路径不调用它（零 admin_alerts 落盘）。上升件自动收口复用 `close_cause` 族单点常量，新增 `CLOSED_BY_CHAIN`。
6. **降噪废止范围**：链入口不分 severity；降级态保留原降噪（critical/major 进 pending、warning/minor 写入即 handled）——降噪是「人工队列」的属性，不是「信号」的属性。
7. **迁移代码化**：存量 pending 收口逻辑作为 daemon 启动 hook（版本哨兵防重跑），在主树由 daemon 执行——不在 worktree 内操作运行时文件（对齐「主树专属写操作不进任务」纪律）。

## Risks

- **链延迟换闭环**：两级自动化把人工感知延迟从「即时告警」变为「链跑完才上升」——单飞队列与配额上限封顶最坏延迟；处置链视图提供过程可见性
- **D6 守卫测试改写遗漏**：`test_arbiter_lane.py` 机械守卫与回扫排除逻辑强耦合，改写不全会假绿——任务单列并要求断言新配额语义（含 dead-man 例外）
- **自环漏判**：链入口来源判定依赖信号发射点标注——发射点全量清点入任务（`_send_human_escalation_alert` 与 `freeze_for_human` 全部调用点），防链成员信号重入
- **dashboard 双页数据竞读**：处置链视图与 alert 页同读 admin_alerts.json——沿用 `alerts_overview` 单读聚合模式，不新增读路径

## 开放点（实现者裁量）

- 复现计数与配额的具体 schema（state 文件字段命名/版本）
- 转单载荷注入 Arbiter prompt 的段落位置与体量上限
- 链队列溢出（>深度上限）时的降级动作（建议最旧低 sev 直达人工+容量告警）
- 上升件 choices 快照时序（落盘快照 vs 前端动态）
