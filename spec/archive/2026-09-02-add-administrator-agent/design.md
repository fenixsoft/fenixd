# Design: add-administrator-agent

## Context

`fix-fenix-token-waste` 已用熔断/健康检查/单实例锁等手段消除了大部分自动重跑循环，但仍有需要 Agent 级判断才能脱困的场景（卡死进程、异常 spec 状态、框架级 bug），以及 Agent 处理不了必须人工介入的事件。目标：让 Fenixd 无人值守时能自愈，人类只处理真正需要人类的事件。

关键约束：用户强成本敏感。因此监视必须零 LLM 成本，Administrator Agent 只在检测到困境时才唤起。

## Goals / Non-Goals

**Goals**
- 零成本的周期性健康监视（有 spec 进行中时）
- 困境 → 按需唤起 Administrator 自主处置
- 无法处置 → 结构化告警 + Dashboard 通知

**Non-Goals**
- 不改变现有 implementer/verifier/planner 流程
- 不让 Administrator 参与日常开发
- 不引入新外部依赖

## Decisions

**D1: 轻量 Python 监视器（零 LLM），困境才唤起 Administrator**
- 监视器是 daemon 内一个线程，每 `admin.interval_minutes` 读本地数据（STATE.md、runs 转录、fenixd.log）做规则检测，不调 LLM。
- 只有检测到困境信号且节流通过时，才用 `claude -p` 唤起 Administrator Agent。
- 替代方案：每 5 分钟跑完整 Agent。否决原因：一天 ~288 次 × $1-2 ≈ $300+/天，且大多结论是"一切正常"。
- 涉及：新增 `core/admin_monitor.py`，`fenixd.py` 启动线程。

**D2: 困境信号规则（可配阈值）**
- 重复失败：30 分钟内同 spec 失败 run ≥3 次
- 状态抖动：10 分钟内 ready↔implementing 切换 ≥3 次
- 卡死：implementing/testing 超 `stuck_threshold_minutes` 无进展
- 熔断滞留：`_merge_streak` ≥ 阈值仍停留
- daemon 连续 ERROR
- 节流：同 spec 同类信号 15 分钟内只唤起一次
- 涉及：`admin_monitor.py`，配置 `admin.*`。

**D3: Administrator 复用 agent_runner 的 claude 子进程模式**
- 新增 `agent_type="administrator"`：`claude -p` + `--permission-mode bypassPermissions` + `--output-format stream-json`，产物写入 `.fenix/runs/admin-*.jsonl`。
- prompt 注入困境详情 + 处置权限清单 + "仅处置不开发"约束。
- 涉及：`core/agent_runner.py:_build_prompt`、`run_administrator()`。

**D4: Administrator 在 main 树直接操作框架**
- 与 implementer 的 worktree 隔离不同：Administrator 是运维角色，修改 Fenixd 自身代码应直接落 main 并 commit（框架自愈代码本就该在主树）。
- 涉及：无代码改动，prompt 约束即可。

**D5: 告警持久化 `.fenix/admin_alerts.json`**
- 统一存升级告警 + 处置记录（append-only JSON 数组）。
- Dashboard 读该文件渲染横幅与列表。
- 涉及：新增 `core/admin_store.py`（或并入 admin_monitor），Dashboard server/data。

**D6: Dashboard 告警横幅**
- 未处理告警存在时顶部横幅：数量、最高 severity、最新摘要；列表 + "标记已处理"。
- 涉及：`core/dashboard/server.py`（/api/alerts）、`static/app.js`、`index.html`。

## Risks / Trade-offs

- [Administrator 有高级权限可能误操作] → 处置前先只读诊断；处置动作全部留痕；杀/重启前先确认目标进程归属
- [Administrator 与 daemon 竞争资源] → 单实例锁已防双 daemon；Administrator 杀 fenixd 后由启动脚本/tmux 自动拉起
- [告警噪音] → 节流冷却 + severity 分级 + 人工可标记已处理
- [Administrator 修改框架后需重启才生效] → 处置记录标注"需重启生效"，监视器下次运行自动重启 daemon（如有必要）

## Migration Plan

1. 新增配置 `admin.enabled`（默认 true）、`admin.interval_minutes`（5）、`admin.agent_model`、`admin.escalation_cooldown_minutes`（15）。
2. 无数据迁移；`.fenix/admin_alerts.json` 新文件即建即用。
3. 回滚：配置 `admin.enabled: false` 即整体停用。

## Open Questions

- Administrator 修改框架代码后是否自动重启 daemon 生效？（倾向：需要时自动重启，重启后恢复进行中 spec）
- 跨项目 Dashboard 是否聚合所有项目的告警横幅？（多项目监控能力已有，可在该项目告警基础上扩展）
