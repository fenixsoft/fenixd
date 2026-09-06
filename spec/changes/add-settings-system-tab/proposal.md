# Proposal: add-settings-system-tab

## Why

`admin.*` 配置段（自愈监视器、重启排水等系统级行为）完全没有设置界面——只能手改 `.fenix/config.yaml`。2026-09-05 重启排水的 `shutdown_drain_seconds` 缺省错配事故（daemon 缺省 1800s 排水、supervisor 缺省 60s 强杀）暴露的正是这类「无界面、易错配、出事才被发现」的配置面缺口。同时新项目模板默认值 `shutdown_drain_seconds: 1800` 对 1-2 小时级 implementer/planner 在飞场景意味着每次重启必等满 30 分钟，需要改为 0（快速停机 + interrupted 标记续做兜底）。

## What Changes

- 设置页新增**「系统」页签**（SystemPanel），收录 5 个 `admin.*` 键：`enabled` / `interval_minutes` / `escalation_cooldown_minutes` / `merge_breaker_threshold` / `shutdown_drain_seconds`，每项带一句话注解
- **`read_config` 白名单扩展 admin 段**（data.py:2852 当前只回 llm/agents/verify——不扩展则保存后回显恒空，add-planner-efficiency 刚判 product-bug 的 verify 段提取遗漏同款缺口）
- 写入校验：非负数字/布尔类型校验，非法值拒绝保存
- 新项目模板 `.fenix/config.template.yaml` 的 `shutdown_drain_seconds` 默认值 **1800 → 0**
- `docs/help/08-config.md` 补 admin 段说明

**不进本 spec**（用户决策）：`admin.workers`（逃生门语义，保持手改）、`admin.stuck_threshold_minutes`（已弃用，run_timeout 派生）、`admin.self_review.*`（已有 SelfReviewPanel）、`admin.agent_model`（兜底语义已被 agents.models.administrator 遮蔽，避免双入口困惑）。

## Capabilities

### New Capabilities

- `settings-system-tab`: 设置页系统页签（admin.* 配置的展示/注解/保存/回显/校验）与模板默认值修正

### Modified Capabilities

（无——spec/specs/ 当前无活跃能力声明）

## Impact

- **前端**：`core/dashboard/static/src/pages/settings/`（新 SystemPanel + index.tsx 注册页签）
- **配置契约**：`core/dashboard/data.py`（read_config 白名单 + write 校验）
- **模板**：`.fenix/config.template.yaml`（admin.shutdown_drain_seconds 1800→0）
- **文档**：`docs/help/08-config.md`
- **回归确认**：read_config 白名单扩展不得影响既有 llm/agents/verify 段的回显
