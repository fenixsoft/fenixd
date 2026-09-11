# Design: add-settings-system-tab

## Context

设置页已有 10 个面板（VerifyPanel/SelfReviewPanel/AgentModelPanel 等），模式成熟：面板组件 + `services/dashboard.ts` 的 getConfig/writeConfig 通道 + `data.py` 的 `read_config`/`write_config`。`read_config` 是白名单提取（data.py:2852，只回 llm/agents/verify）——admin 段扩展是本 spec 的契约核心；`write_config(scope_root, patch, scope="project")` 写项目级 `.fenix/config.yaml`。

`admin.*` 键的消费方与语义已逐一代码核实（2026-09-06，见注解表）；`admin.self_review.*` 已有 SelfReviewPanel，`admin.workers`、`admin.stuck_threshold_minutes`（弃用）、`admin.agent_model`（兜底语义被 agents.models.administrator 遮蔽，避免双入口困惑）经用户决策不进界面。

## Goals / Non-Goals

**Goals**
- 系统页签 = admin.* 的单一界面入口，注解即文档
- read_config admin 段白名单扩展（回显闭环）
- 模板默认值 1800→0（快速停机为开箱缺省）

**Non-Goals**
- 不做 admin.workers 界面（逃生门语义，保持手改）
- 不动 admin.stuck_threshold_minutes（弃用键）
- 不做 admin.agent_model 界面（兜底键，已被 agents.models.administrator 遮蔽；避免与 AgentModelPanel 双入口互相覆盖的困惑）
- 不改 daemon/supervisor 的排水逻辑本身（配置默认值治理已在运行态完成）

## Decisions

### D1: 注解文案（设置界面注解表，实现时逐条进 SystemPanel）

| 键 | 界面注解 |
|---|---|
| `admin.enabled` | 自动自愈总开关：关闭后困境（卡死/反复失败/预算耗尽）不再自动唤起 Administrator 处置，界面手动运维调用不受影响 |
| `admin.interval_minutes` | 自愈监视器巡检周期（分钟）：每这么久扫描一次困境信号；也参与卡顿判定的宽限期计算（间隔×2） |
| `admin.escalation_cooldown_minutes` | 同一 spec 同类困境信号的唤起冷却（分钟）：冷却期内不重复唤起，避免同一问题反复烧钱 |
| `admin.merge_breaker_threshold` | merge 熔断阈值：同一 spec merge-back 连续失败达该次数仍滞留时触发熔断信号（缺省沿用 agents 同名键=2） |
| `admin.shutdown_drain_seconds` | 计划性重启排水窗口（秒）：restart_request 后等在跑任务自然收工的上限，0=立即快速停机（在飞任务标记中断、重启后续做）；supervisor 强杀等待=本值+120s |

### D2: agent_model 不进界面

`admin.agent_model` 为 legacy 兜底键（解析链：agents.models.administrator > admin.agent_model > 默认网关，runner.py:919-921），当前被角色分配遮蔽。经用户决策不进系统页签，避免与 AgentModelPanel 的 Administrator 条目形成双入口。

### D3: 校验落点

校验放 `write_config` 的 admin 段分支（服务端权威），前端仅做输入类型提示；错误返回形态沿用现有 config 写入校验（非法值拒绝 + 明确消息），与 `shutdown_drain_seconds` 既有校验（config.py:256）同风格。

### D4: read_config 白名单扩展形态

admin 段返回 5 键 + 各自缺省值（与 llm/agents 段的「缺省填充」形态一致），不透传未知 admin 键（保持受管语义）；`self_review` 子段不由本页签管理，不纳入返回。

## Risks / Trade-offs

- [read_config 白名单扩展影响既有段] → 扩展只增不改，现有段返回结构逐字段不变；回归 test_config / test_dashboard_api
- [agent_model 与 agents.models.administrator 双入口困惑] → 注解明示遮蔽关系（D2），不做联动
- [模板改 0 后新项目排水行为变化] → 0=快速停机+interrupted 续做是 interrupt-recovery-preserve 设计路径，语义安全；有特殊需求的项目可手改大值
- [fast-track 单 agent 覆盖前端+契约+模板+docs] → 交付物清单明确到文件，验证场景 5 条可机械对账

## Migration Plan

无数据迁移。存量项目 config 不动（运行态已手动改 0）；模板只影响 fenix-init 新项目渲染。回滚 = revert。

## Open Questions

（无——语义已全部代码核实）
