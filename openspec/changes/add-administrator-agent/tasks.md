# Tasks: add-administrator-agent

## 1. admin-health-monitor

- [ ] 1.1 新增 `core/admin_store.py`：`.fenix/admin_alerts.json` 读写（升级告警 + 处置记录 append + 标记已处理）
- [ ] 1.2 新增 `core/admin_monitor.py`：困境检测规则（重复失败/状态抖动/卡死/熔断滞留/daemon ERROR），纯本地数据、零 LLM
- [ ] 1.3 `admin_monitor.py` 节流/冷却：同 spec 同类信号 `escalation_cooldown_minutes` 内只唤起一次
- [ ] 1.4 `fenixd.py` 启动监视线程：按 `admin.interval_minutes` 运行，仅在存在进行中 spec 时检测，`admin.enabled` 可整体开关
- [ ] 1.5 `config.py` 支持 `admin.*` 配置段（enabled/interval_minutes/agent_model/escalation_cooldown_minutes）

## 2. administrator-agent

- [ ] 2.1 `agent_runner.py` 新增 `run_administrator()` + `_build_prompt` 的 `administrator` 分支（困境详情 + 处置权限清单 + 仅处置不开发约束）
- [ ] 2.2 监视器→唤起调度：检测到困境且节流通过 → `run_administrator()`，产物写 `.fenix/runs/admin-*.jsonl`
- [ ] 2.3 Administrator 处置完成后将处置记录写入 `admin_alerts.json`

## 3. human-escalation-alerts

- [ ] 3.1 Dashboard server 新增 `/api/alerts`（读取 + 标记已处理）
- [ ] 3.2 Dashboard UI：顶部告警横幅（未处理数/severity/摘要）+ 告警列表 + 标记已处理按钮
- [ ] 3.3 `.gitignore` 追加 `.fenix/admin_alerts.json`

## 4. 测试与验证

- [ ] 4.1 `admin_monitor` 检测规则单元测试（重复失败/抖动/卡死/节流）
- [ ] 4.2 `admin_store` 读写 + 标记已处理单元测试
- [ ] 4.3 Dashboard alerts API 单元测试
- [ ] 4.4 运行 `python3 -m pytest tests/ -q` 全绿
