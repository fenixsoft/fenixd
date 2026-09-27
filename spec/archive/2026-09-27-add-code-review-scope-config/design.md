# add-code-review-scope-config 设计

## Context

周期性代码审查车道（add-code-review-agent-and-quality-tab 交付）的范围硬编码为 `window`：`core/admin_monitor.py` 周期触发路径中 `collect_manifest(self.project_root, scope="window", window_start=window_start)` 与 `run_code_review(..., scope="window")` 两处字面量。手动触发已有 full/window 两按钮，周期审查无法选全仓，行为不对称。

配置读取点已收敛：`ConfigLoader.get_code_review_config()`（core/config.py:1384）统一返回 `admin.code_review` 段并补缺省（`enabled=False`、`max_files=500`）；设置页保存链的受管键清单（`core/dashboard/data/config_admin.py`）已含 `admin.code_review` 整段。

## Goals / Non-Goals

- Goals：范围可配（window | full）、缺省零行为变更、两档共用调度守卫、设置页 UI 对齐手动按钮语义。
- Non-Goals：不改手动触发路径；不改台账/审计数据结构（manifest 内 scope 字段既有）；不引入第三种范围档位；不做按项目差异化的范围调度。

## Decisions

### D1 配置键挂在既有 `admin.code_review` 段下（`scope` 键），缺省 `window`

不新增顶层段、不新增受管键条目（整段白名单已覆盖）。缺省值在 `get_code_review_config` 统一补齐（对齐既有 `enabled`/`max_files` 的缺省模式），非法值（非 `window/full` 字面量、非字符串）回退 `window`——巡检路径 MUST NOT 因配置脏值中断。

### D2 scope 只改变「收集什么」，不改变「何时触发、算谁跑的」

`review_kind` 保持 `scheduled`（台账审计口径：periodic 触发与手动触发的区分依据是 review_kind，不是 scope；scope 在 manifest 审计字段里如实记录）。full 档 `window_start=None` 传给 `collect_manifest` 与 `run_code_review`——`run_code_review` 既有签名已支持（`manual_full` 即此形态），无需改函数签名。收尾全仓核销例外（D5「只增不核销」的唯一例外）按 `review_kind == "manual_full"` 判定（`core/agent_runner/maintenance_runs.py:922`），与 scope 无关——周期 full 档（scheduled）MUST NOT 触发 `resolve_snapshot` 全仓核销，实现时不得让 scope 参与该判定。

### D3 UI 语义命名对齐手动按钮

下拉文案用「当期审查 / 全库审查」（与项目页按钮一致），不引入第三套叫法（如「增量/全量」）——本仓已有文案-按钮对齐惯例（用户 2026-09-22 刚统一过按钮文案）。设置页该区块既有开关/数字输入的布局与保存流不变，仅多一个 Select。

### D4 窗口语义键只在 window 档生效

「周期窗口与自省同源」的 window_start 计算保留在 window 档；full 档不读自省状态（但**不改变自省本身**——两者只是共享触发时点，自省的窗口写状态照常）。避免「full 档还要不要维护 last_run_at」的歧义：维护（自省车道自己的事，与本车道无关），本车道 full 档只是不消费它。

## Risks / Trade-offs

- full 档在大仓上更贵：`max_files` 截断既有（缺省 500），UI 上在区块内保留既有上限说明文案即可，不新增防呆。
- 用户切 full 后当天已防重则次日生效——与既有「同自然日防重」一致，无需特判。
- 升级期旧配置（无 scope 键）= 缺省 window = 现状，零迁移。

## Migration Plan

纯增量配置键，缺省值即现状；部署顺序自由（读侧缺省回退兜底）。

## Open Questions

- 无。
