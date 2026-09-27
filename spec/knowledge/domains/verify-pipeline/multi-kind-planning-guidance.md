# 多类型场景规划指引
<!-- knowledge: capability=multi-kind-planning-guidance rev=1 sources=spec/archive/2026-09-12-add-verify-multi-kind-runner -->

planner 侧的多形态（web/cli/api）场景规划引导、词表权威源约束与验收门打回路径，使非 web 交付有合规的出题通路。

## 现行规则

- kind 选择判定树（planner 提示词内）：页面/交互交付→`web`；HTTP 端点交付→`api`；命令/脚本/落盘交付→`cli`；混合交付按交付物拆分场景、各自 kind，跨 kind 流程用 `depends_on` 串接。模板简述三套词表的步骤/断言/字段口径与 kind 特异规则（cli 非零退出不判失败、api 响应命名捕获）。
- 词表权威源单一：提示词词表段落标注权威源为 `core/verify_engine/scenarios.py` 的 VALID 常量，提示词只做引导摘要、代码校验为准；词表扩展须同步代码常量与模板摘要，不得在提示词中独立维护可漂移的完整枚举。摘要缺失不导致误拒（按代码词表执行），代码词表外的产出必被验收拒绝。
- API 验证通道治理：HTTP 端点验证使用 `api` 场景，不得用 web 场景 navigate 到端点 `text_contains` 断 JSON 文本凑合；web 场景仅承担页面/交互验收。
- 验收门打回路径：验收错误消息可指导修复——未知 kind / 步骤不属于本 kind 词表 / 必填字段缺失 / 场景集含 web-api 但无 serve 配置，均带「支持: …」词表速查打回 plan；退回上限复用既有机制，不新增状态机状态。
- 取证措辞中立化：verifier、planner-judge、fast-track 提示词的取证措辞为「证据（截图 / 命令输出 / HTTP 响应体）」，triage 归因指引同步；CLI/API 场景无截图属合法形态，不因无截图判证据不足或 inconclusive。
- 文档同步：docs/help 含多形态验证章节（三 Runner、契约形态反推、kind 选择），无「验证必须起 HTTP 服务／验证=浏览器」类过时断言。

## 溯源

- 2026-09-12 add-verify-multi-kind-runner — 新增 planner kind 判定树与词表引导（权威源标注 scenarios.py 常量）、验收门打回消息带词表速查、verifier/judge/fast-track 截图措辞中立化、docs/help 多形态验证文档
