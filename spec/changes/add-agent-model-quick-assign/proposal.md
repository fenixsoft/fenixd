## Why

Agent 角色已达 13 个（implementer、planner-plan、verifier、code-review 等），在设置页「Agent 模型分配」逐个角色配置 provider + 模型候选链成本高、易漏配；而「全部角色统一为同一组模型」是常见运维动作（切换网关、灰度新模型、统一降级）。当前只能逐卡编辑，或用卡片上的复制/粘贴逐角色搬运，且无法一次把同一分配投放到多个项目的项目级作用域——需要切换作用域逐个重复操作。

## What Changes

- 设置页「Agent 模型分配」页签增加「快速分配」按钮与弹窗。
- 弹窗内编辑一份分配模板：角色默认模型（可空）+ 多行 provider + 模型候选链（与单角色分配同语义、同回退顺序）。
- 应用时把全部已知 Agent 角色（当前 13 个，以 `ConfigLoader.KNOWN_AGENT_TYPES` 为准）的 `agents.models` 整体覆盖为该模板（原各角色分配被替换，不合并）。
- 作用域选择：本作用域（当前设置页所选用户级/项目级）或指定项目（多选已注册项目，逐项目写入其项目级配置）。
- 目标项目缺少所选 provider 定义时，自动把当前作用域的有效 provider 定义复制到该项目 `llm.providers`（保留项目既有定义，不覆盖同名），避免「引用了不存在的 provider」写入失败。
- 逐目标写入并逐项回报结果：单目标失败不影响其他目标（部分成功可见），本作用域写入成功后面板自动刷新。
- 应用前确认：提示会覆盖全部角色分配；若当前面板有未保存修改，提示将被丢弃。
- 后端新增快速分配写入端点（服务端逐目标校验 + 原子写）；不改变 daemon 运行期模型解析与配置格式。

## Capabilities

### New Capabilities

（无）本需求是既有能力的扩展，不引入独立的新能力：行为面归入既有 `llm-model-assignment` 能力（Provider 注册表 + 按角色模型分配 + Dashboard 配置编辑）。

### Modified Capabilities

- `llm-model-assignment`（既有能力，归档于 `spec/archive/2026-09-02-add-fenix-config/specs/llm-model-assignment/spec.md`）：追加「快速分配」需求组——一次编辑模板后整体覆盖全部 Agent 角色分配、支持本作用域/指定项目作用域、目标项目 provider 自动补齐、逐目标结果与失败可见、应用后刷新与提示。

## Impact

- 前端：`core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx`（入口按钮、弹窗状态与提交）；新增快速分配弹窗组件（如 `core/dashboard/static/src/pages/settings/components/QuickAssignModal.tsx`）；`core/dashboard/static/src/pages/settings/index.tsx`（传入项目列表、应用后刷新回调）；`core/dashboard/static/src/services/dashboard.ts`（快速分配 API 调用）。
- 后端：`core/dashboard/routes/settings_routes.py`（新 handler）、`core/dashboard/routes/base.py`（POST 路由注册）、`core/dashboard/data/config_admin.py`（快速分配写入、provider 自动补齐、逐目标结果；复用 `_write_config_locked` 的校验与原子写）。
- 测试：`tests/test_dashboard_api.py`、`tests/test_dashboard_data.py` 新增快速分配用例；`tests/test_provider_ref_validation.py` 回归。
- 不改变：`agents.models` 配置格式、daemon 运行时解析与校验语义、其他配置页签。
- 无数据库/配置文件迁移。
