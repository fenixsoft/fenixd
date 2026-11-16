# 场景时长字段单位契约

<!-- knowledge: capability=scenario-timeout-unit-contract rev=1 sources=spec/changes/evo-scenario-timeout-unit-contract -->

场景步骤级时长字段（`timeout` / sse_connect `duration`）的单位与量级口径：全链以秒为唯一单位、共享同一上限常量，生成侧提示词显式承载约定，写前预校验按量级拦截并为毫秒误写提供换算嫌疑提示。

## 规则

- **单位为秒、上限 1800 秒**：场景步骤级 `timeout`（cli `run`、api `http_request` 等步骤超时）与 api `sse_connect` 的 `duration`（事件收集窗口）单位均为**秒**，共用同一上限常量 `MAX_STEP_TIMEOUT`（1800 秒 = 30 分钟）。两字段是同构暴露面（运行层都会按给定值如实等待、单场景占住并行槽挂起整轮验证），单位约定与上限必须同款覆盖两者，不得只约定其一。合法示例值 120 / 900 / 1500。
- **秒是唯一口径、schema 不设单位字段**：时长字段不引入「值 + 单位」二元形态，无双单位兼容面；存量与新增场景一律按秒解读。
- **生成侧提示词显式承载单位约定**：planner-plan 提示词 MUST 明示时长字段的单位、上限与合法示例值，MUST NOT 留空单位语义让规划器自行猜测。该约定带防漂移守卫：单测断言提示词约定行在场，且其声明的上限数值与校验层 `MAX_STEP_TIMEOUT` 常量一致（提示词不维护第二份可漂移枚举，静态文本里的数值必须锚定常量做一致性断言）。
- **写前预校验量级拦截**：验收层校验对 `timeout`/`duration` 超过上限的条目报错，报错回显数值与上限；非法条目不落盘，按既有写前预校验闸门语义处置（逐条剔除留痕、全部非法时整批拒绝退回 plan 重排）。整批毫秒形态误写会烧掉一整轮重排，提示词前置约定压低该错位的触发频率，量级门保持为最后防线（提示词为自然语言约定、无运行时强制）。
- **毫秒形态换算嫌疑提示**：超上限且值可被 1000 整除时，报错追加「疑似毫秒，建议除以 1000 后重写为秒」，让退回重排的规划器下一轮直接按秒改写；秒级超限（不可被 1000 整除，如 2400）只回显超限事实、不附嫌疑提示。嫌疑提示为非阻断建议，对恰好可被 1000 整除的秒值（如 2000）会误提示——概率低且不改变拦截结果，属可接受误报。
- **运行层镜像拦截不带嫌疑提示**：cli_runner / api_runner 的运行层对超上限值有同款拦截（读同一 `MAX_STEP_TIMEOUT` 常量），报错文案保持仅回显数值与上限——退回重排回路消费的是验收层报错，嫌疑提示只在验收层附加。

## 代码锚点

- 上限常量 + 换算嫌疑提示 + 验收层量级拦截：`core/verify_engine/scenarios.py`（`MAX_STEP_TIMEOUT`、`_ms_unit_hint`、`_validate_typed` 的 timeout/duration 超上限分支）
- 提示词单位约定：`agents/planner-plan.md`（时长字段单位为秒约定段）
- 运行层镜像拦截：`core/verify_engine/cli_runner.py`、`core/verify_engine/api_runner.py`
- 守卫测试：`tests/test_scenario_timeout_unit_contract.py`

## 溯源

- 2026-11-17 evo-scenario-timeout-unit-contract（spec/changes/evo-scenario-timeout-unit-contract/） — 新建本能力页：时长字段秒单位契约（planner-plan 提示词显式约定 + 与 `MAX_STEP_TIMEOUT` 常量的防漂移一致性守卫）、超上限报错的疑似毫秒换算嫌疑提示（值可被 1000 整除才附、运行层镜像文案不变）；量级上限与写前预校验闸门行为本身维持现状
