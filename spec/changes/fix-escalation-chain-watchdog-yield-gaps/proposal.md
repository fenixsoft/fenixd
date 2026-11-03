## Why

处置链（add-escalation-chain-admin-arbiter）落地后首例真实链路事件（2026-11-03
`add-knowledge-inbox-pipeline::verify_env_blocked`）暴露三个结构性缺口，均已实证：
(1) AdminMonitor 孤儿看护对链在办件重复出件——链已转派 arbiter 在飞调查时，看护
仍按 pending 超时直发 critical 人工告警（早链终点 3 分钟），违背「人工只是链终点
失败后的例外出口」的门面承诺，且告警归因模板（「疑似 daemon 重启/崩溃」）与 run
终态证据（frozen-terminated）不符，误导排查方向；(2) spec 冻结与链头 Admin 派发
竞态（冻结落盘早 ~100ms）使 admin run 秒死空壳仍烧一次配额（失败 1/2）；(3) 链
deferred 让行后无唤醒路径——被让行的非链成员 run 死亡不回喂链，链静默挂起直到
daemon 重启回扫才恢复（本例空转 5 分钟）。三缺口共享修改点（让行/入链段 + 孤儿
接管路径），合并立项一次治完。

## What Changes

- **孤儿看护链痕抑制**：孤儿接管路径（pending 超时升级分支）开火前查链痕——
  链 in_flight 区有同签名在办条目、或让行留痕、或 arbiter 单飞队列同签名在飞
  时，抑制升级（不产人工告警、不终结 pending disposition）；全部链痕消失（被
  reap/超时）且 pending 仍超时时照常升级，兜底语义保留
- **链让行留痕**：deferred 分支不再整条清除 in_flight 登记，改记
  `phase: deferred` 条目（含被让行对象标识与时间戳）；看护巡检扫描让行条目——
  被让行 admin run 已终态且信号未收口时重新触发链派发（复用回扫管线，挂既有
  巡检节拍），让行条目超时则照常 reap，消除「静默挂起等复发」
- **冻结竞态防烧配额**：链头 Admin 派发前查 spec frozen 态——frozen 时不派发
  不计配额（挂 deferred 留痕等解冻后由看护扫描重派）；防御纵深：run 终态为
  frozen-terminated（0 轮空壳击杀）的失败不计入配额计数（视为未尝试而非失败）
- **告警归因取实证**：孤儿升级告警的 description 按 run 文件终态证据生成归因
  （frozen-terminated / killed / 死因不明），替代「疑似 daemon 重启/崩溃连带杀死
  admin」固定模板；既有 interrupted=已知中断不告警口径不变

## Capabilities

### New Capabilities

（无——本变更全部为既有能力 requirement 变更）

### Modified Capabilities

- `escalation-chain`: 三处 requirement 变更——(a) 入链派发前 frozen 预检与
  frozen-terminated 不计配额的配额语义收窄；(b) deferred 让行从「静默丢弃等
  复发」改为「in_flight 留痕 + 看护扫描重派或超时上升」；(c) 让行条目纳入既有
  in_flight 超时 reap 机制
- `human-escalation-alerts`: 孤儿升级口径两处变更——(a) 开火前链痕抑制（链
  在办/让行留痕/arbiter 在飞任一命中即抑制）；(b) 告警归因按 run 终态证据生成，
  废弃固定归因模板

## Impact

- `core/pm_engine/escalation_chain.py`：入链 frozen 预检、deferred 留痕、
  frozen-terminated 配额语义
- `core/admin_monitor.py`：孤儿接管链痕抑制、让行条目扫描重派、告警归因生成
- `.fenix/escalation_chain_state.json` in_flight 区条目形态扩展（运行时文件，
  gitignored，向后兼容读旧形态）
- 测试：`tests/test_escalation_chain.py`、`tests/test_admin_disposition_reschedule.py`
  （孤儿路径既有用例归属）扩展竞态/抑制/重派/归因用例
- daemon 行为变更，合并后需重启生效（restart_request 交付项）
- 取证与候选修法全文：`spec/knowledge/_inbox/escalation-chain-orphan-watchdog-double-path.md`
