## Why

Fenixd 无人值守运行时，Agent 可能陷入自身无法脱困的困境：merge 失败死循环（曾烧掉 $23、965 轮）、spec 卡死、重复重试烧钱、框架级 bug。此前这类问题只能靠人工盯日志介入。需要一个不参与开发的 Administrator 角色：低成本持续监视，检测到困境时自动介入处理，实在处理不了才升级给人类。

## What Changes

- **轻量健康监视器**（daemon 侧，纯 Python，零 LLM 成本）：有 spec 进行中时每 5 分钟检查一次 STATE.md / runs 转录 / daemon 日志，检测：重复失败与重试烧钱、spec 状态空转（ready↔implementing 抖动）、卡死超时、merge 反复失败、框架异常
- **Administrator Agent**（按需唤起）：监视器检测到困境时，唤起一个 `claude` 子进程扮演 Administrator，拥有高级权限自主处置：
  - 杀死/重启卡死的 Agent 与 fenixd
  - 发起自己的 SPEC、修改 Fenixd 自身代码
  - 发起 git 清理 / commit / stash / worktree 管理
  - 重置/修复 spec 状态
- **人工升级通知**：Administrator 也处理不了的事件，写入结构化告警记录，Dashboard 打开时醒目通知人类介入
- 配置项：`admin.enabled`、`admin.interval_minutes`、`admin.agent_model`、`admin.escalation_thresholds`

## Capabilities

### New Capabilities

- `admin-health-monitor`: daemon 侧轻量健康监视器，零成本周期性检测困境信号
- `administrator-agent`: 按需唤起的 Administrator Agent，拥有高级权限自主处置 Agent 无法脱困的问题
- `human-escalation-alerts`: 需人工介入事件的持久化告警 + Dashboard 通知

### Modified Capabilities

（无。全部为新增能力。）

## Impact

- **代码**：`fenixd.py`（新增监视调度线程）、`core/agent_runner.py`（Administrator agent 类型）、新增 `core/admin_monitor.py`、`core/dashboard/`（告警 UI 与 API）
- **配置**：`config.yaml` 新增 `admin.*` 段
- **运行数据**：新增 `.fenix/admin_alerts.json`（告警持久化，gitignore）
- **权限**：Administrator Agent 以 `--permission-mode bypassPermissions` 运行，拥有完整 Bash/文件/git 权限；其行为由 prompt 约束为"仅处置困境，不开发功能"
