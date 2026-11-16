# Proposal: add-escalation-chain-admin-arbiter

## Why

2026-11-02 dsh-plugins 两条人工告警取证暴露三个结构性问题：升级信号结构性不走 Arbiter（白名单 10 信号覆盖不了 `inconclusive_loop`/`warning_stale_triage`）、已解决事故的告警永久滞留人工队列（原始 escalation 无关联键收口不了）、自动化车道各自为战没有统一的处置链次序。用户 2026-11-03 定调：**人工裁决从「默认终点」降级为「例外出口」**——全部升级边信号默认走自动化处置链（Admin→Arbiter），人工只在两级自动化都失败后出场，且出场即带完整调查背景。

## What Changes

- 升级发射咽喉改道：`_send_human_escalation_alert`/`freeze_for_human` 触发的信号默认入**处置链**（Admin 先行），不再立即落人工队列；人工队列只收链终点（Arbiter 失败）的上升件
- 处置链语义（设计文档用户 7 定调 + 链语义细则 8 条）：链入口按信号来源判定（防自环）；Admin=受限环境运维（2 次/签名配额、`handoff: arbiter` 超范围转单、side-effects 解冻）；Arbiter=全局拍板（复现配额 2 次、预算豁免拍板动作面、dead-man 例外）；失败双轨（自判失败/复现第 3 次）
- 触发面反转：既有白名单+排除表机制替换为黑名单配置化（初始空集 kill switch）；`arbiter.enabled=false` 或链失能时整体退回现状（fail-open 直达人工）
- 既有「同签名只自主处置一次」纪律（D6/`_dispositioned`/`_ledger_sigs`）被配额制正式取代（机械守卫测试同步改写）
- 闭环语义：链内任一级处置成功 = 信号收口 + spec 状态恢复可运行（框架侧 side-effects 显式 status 解冻，Admin 获得同型执行路径）；上升件携带全链关联键
- 存量迁移：daemon 启动一次性迁移，能判定「底层已闭环」的旧 pending 告警自动收口（`close_cause=migrated`）
- 可见性：SPEC 时间轴扩展为全链节点（Admin/Arbiter 每次尝试+配额计数+复现事件+上升件）；Dashboard 新增自动化处置链视图（在办/队列/配额水位；spec=null 信号归组于此）；新配置项（两级配额/复位窗/黑名单）带设置界面
- 降噪分级废止：链入口不按 severity 过滤（minor 预算循环信号也入链）；降级态保留原降噪

## Capabilities

### New Capabilities

- `escalation-chain`: 处置链路由与配额语义——链入口来源判定、Admin→Arbiter→人工次序、双车道 2 次/签名配额与 7 天/状态迁移复位、Admin handoff 转单、Arbiter 预算拍板面、黑名单 kill switch、链级失能 fail-open、闭环 side-effects、存量迁移
- `chain-observability`: 处置链可观测与配置——时间轴全链节点富展示、Dashboard 自动化处置链视图、链配置（配额/复位窗/黑名单）设置界面

### Modified Capabilities

- `arbiter-lane`: 触发面从白名单枚举改为处置链默认入链+黑名单排除；同签名「只派发一次」改为「配额 2 次」
- `human-escalation-alerts`: 升级告警从「发射即落人工队列」改为「默认入链，仅链终点失败上升落队列；上升件附全链痕迹」

（时间轴扩展以新能力 `chain-observability` 的 ADDED Requirement 承载，既有 `timeline-arbiter-visibility` 的 arbiter 节点联查语义不变、不另立 delta。）

## Impact

- `core/pm_engine/`：`family.py`（发射咽喉改道）、`arbiter.py`（触发面/配额/拍板面）、新 `escalation_chain.py`（链派发器与配额状态）、`budget.py`（Arbiter 预算豁免动作面挂点）
- `core/adjudication_narrative.py`：让位判定方向反转（链头派发判定）
- `core/admin_store.py` / `core/admin_monitor.py`：上升件关联键与 close_cause 族；看护对象扩展全链在办件
- `agents/administrator.md` / `agents/arbiter.md` / `core/agent_runner/prompt_builder.py`：handoff 契约段、转单载荷注入
- `core/config.py`：新配置键（配额/复位窗/黑名单）
- `core/dashboard/`：`data/timeline.py`、`data/admin_alerts.py`、新处置链视图页与设置区块（`static/src/pages/`）、`static/dist` 构建产物（reference）
- tests：`test_arbiter_lane.py`（守卫改写）、`test_timeline_arbiter_visibility.py`、新 `test_escalation_chain.py` 等
- 依赖：`add-harness-default-key-fallback`（回落先落地，链 spawn 开箱可用）
