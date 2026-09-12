# multi-kind-planning-guidance — planner 引导、验收门与文档

## ADDED Requirements

### Requirement: planner kind 选择指导

`agents/planner-plan.md` SHALL 增加 kind 选择判定树：页面/交互交付→`web`；HTTP 端点交付→`api`；命令/脚本/落盘交付→`cli`；混合交付按交付物拆分场景、各自 kind、跨 kind 流程用 `depends_on` 串接。模板 SHALL 简述三套词表的步骤/断言/字段口径与各 kind 特异规则（cli 非零退出不判失败、api 响应命名捕获）。

#### Scenario: 混合交付场景规划
- **WHEN** planner 面对含「新端点 + 展示该端点数据的页面」交付的 spec
- **THEN** 产出的场景集含 api 场景（端点验收）与 web 场景（页面验收），并以 depends_on 表达数据先后

#### Scenario: 纯 CLI spec 场景规划
- **WHEN** planner 面对交付物为 CLI 命令的 spec
- **THEN** 产出 `kind: cli` 场景（run 步骤 + CLI 断言），不包含 navigate/DOM 断言

### Requirement: 词表权威源单一

planner 提示词中的词表段落 MUST 明确标注权威源为 `core/verify_engine/scenarios.py` 的 VALID 常量；提示词只做引导摘要，代码校验为准。词表扩展时 MUST 同步更新代码常量与模板摘要，MUST NOT 在提示词中独立维护一份可漂移的完整枚举。

#### Scenario: 摘要与代码漂移不产生假通过
- **WHEN** planner 产出提示词摘要中未提及、但代码词表合法的断言类型
- **THEN** 该断言按代码词表正常执行（摘要缺失不导致误拒）；反之产出代码词表外的类型必被验收拒绝

### Requirement: API 验证通道治理

planner 指导 MUST 明确：HTTP 端点验证使用 `api` 场景，不得再用 web 场景 navigate 到端点 `text_contains` 断 JSON 文本凑合（治理 mock_api 断流假阴性放大器暴露面）。

#### Scenario: 端点验证不再借道浏览器
- **WHEN** planner 为含端点交付的 spec 生成场景
- **THEN** 端点断言落在 api 场景中；web 场景仅承担页面/交互验收

### Requirement: 验收门打回路径

验收错误消息 MUST 可指导修复：未知 kind / 步骤不属于本 kind 词表 / 必填字段缺失 / 场景集含 web-api 但无 serve 配置，均带「支持: …」词表速查打回 plan；退回上限机制复用现有，不新增状态机状态。

#### Scenario: 打回消息带词表速查
- **WHEN** planner 产出含未知断言类型的场景集
- **THEN** 验收错误消息列出该 kind 支持的全部断言类型，plan 侧无需查询源码即可修正

### Requirement: 提示词措辞中立化

`agents/verifier.md`、`agents/planner-judge.md`、`agents/fast-track.md` 中的取证措辞 SHALL 由「截图」中立化为「证据（截图 / 命令输出 / HTTP 响应体）」，triage 归因指引同步；CLI/API 场景无截图属合法形态，MUST NOT 因无截图被判定证据不足。修改 agents 模板 MUST 遵循既有双落点约定（先 merge main + merge-tree 自证零冲突）。

#### Scenario: 无截图场景通过证据合规检查
- **WHEN** cli 场景失败，assertion_triage 证据引用命令输出而非截图
- **THEN** 裁决链证据合规检查通过，不因缺截图判 inconclusive

### Requirement: docs/help 验证文档更新

`docs/help/` SHALL 随本能力同步更新：`05-verification.md` 增加多形态验证章节（三 Runner、契约形态反推、kind 选择）、`08-config.md` 核对 verify.yaml 契约说明、`02-concepts.md` 与 `01-quick-start.md` 核对验证相关表述；文档中「验证=浏览器」类表述 SHALL 中立化。

#### Scenario: 文档与实现一致
- **WHEN** 实现合入后查阅 docs/help/05-verification.md
- **THEN** 文档描述三套 Runner 与纯 CLI 无 serve 形态，无「验证必须起 HTTP 服务」类过时断言
