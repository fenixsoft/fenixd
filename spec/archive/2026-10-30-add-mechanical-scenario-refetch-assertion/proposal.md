## Why

add-command-center 的 BUG-1（项目筛选切换后各屏 0 新请求、滞留旧数据最长 60s，LLM 验证轮以 performance 网络日志实证的 major 缺陷）在机械场景套件中**永远无法暴露**：`cc-web-pipeline-filter` 只断言筛选 UI 回显，引擎无「交互后网络请求」断言能力。凡属「交互触发重拉取/触发副作用请求」类缺陷，机械验证结构性失明——这类缺陷只能靠昂贵的 LLM 验证轮偶然发现，且发现后无法被回归锁定。

## What Changes

- verify_engine web 场景步骤新增网络请求断言能力：交互步骤可携带 `expect_network` 期望（URL 模式 + 最少请求数），引擎在步骤执行窗口经 playwright 网络监听收集请求并断言，失败明细含实际捕获计数与样例 URL
- 场景契约校验白名单同步放行新字段（「未知操作/未知字段」验收门）
- planner 出题 prompt 契约段补能力声明（ agents/*.md 契约段，改 prompt 先 merge main 既有口径），使后续出题自然产出 refetch 类场景（如：点击项目筛选 → 期望 ≥1 个 `/api/command-center/` 请求）

## Capabilities

### New Capabilities
- `scenario-network-assertion`: 机械 web 场景的交互后网络请求断言——「点了但没拉数据」类缺陷可被机械验证暴露与回归锁定

### Modified Capabilities

## Impact

- `core/verify_engine/browser.py`：步骤执行窗口网络监听与断言（playwright page route/response 事件收集）
- `core/verify_engine/scenarios.py`：场景契约校验点（「未知操作，支持: …」白名单 `_validate_web` 与 `TestStep` 步骤模型所在，评审实测：该白名单在 scenarios.py 而非 pipeline.py，pipeline.py 仅编排/热重载无词表校验）：新字段放行、形态校验与步骤字段解析/回环
- `agents/*.md` planner 契约段：新能力声明（一句，附最小示例）
- 新增 `tests/test_verify_engine_network_assertion.py`
