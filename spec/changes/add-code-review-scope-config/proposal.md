# add-code-review-scope-config

## Why

周期性代码审查（scheduled）的审查范围当前**硬编码为窗口模式**（`admin_monitor.py` 中 `collect_manifest(scope="window")` 与 `run_code_review(scope="window")` 两处字面量），用户无法选择审查全仓库。而手动触发已有「全库审查 / 当期审查」两个按钮（scope full / window）——周期审查缺一个与之对应的范围配置，行为不对称。

## What Changes

- 新增配置键 `admin.code_review.scope`（`window` | `full`，缺省 `window`——与现状逐字节一致，向后兼容；非法值回退缺省）。
- 设置页「质量」页签「周期性代码审查」区块新增「审查范围」下拉：`当期审查（window）` / `全库审查（full）`，与项目页手动触发按钮语义对应。
- `admin_monitor` 周期触发路径读取该配置：`window` 走既有窗口收集（`window_start` 同源自省）；`full` 走全仓收集（`window_start=None`，`review_kind` 保持 `scheduled`，manifest 内 scope 审计字段如实记录 `full`）。`max_files` 上限对两种范围同样生效（既有截断逻辑不动）。
- 配置模板 `config.template.yaml` 的 `admin.code_review` 注释示例段补 `scope` 行。

## Capabilities

### New Capabilities

<!-- 无新增能力：本变更是对既有周期审查能力的需求级扩展。 -->

### Modified Capabilities

- `code-review-agent`: 「周期窗口与自省同源」requirement 扩展——审查范围（scope）可经 `admin.code_review.scope` 配置为窗口（缺省，语义不变）或全仓；窗口起点同源自省的既有语义仅在 window 档生效，调度守卫（自然日防重 / run_at / enabled 开关）两档完全一致。

## Impact

- `core/config.py`（`get_code_review_config` 缺省值与合法性校验）
- `core/admin_monitor.py`（周期触发两处 scope 取值改读配置）
- `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`（下拉 UI + 回显 + 保存）
- `.fenix/config.template.yaml`（模板示例补键；仓库受控模板，git 追踪，交付清单 kind=modify）
- 无状态机变更、无数据迁移；缺省值保证零行为变更。
