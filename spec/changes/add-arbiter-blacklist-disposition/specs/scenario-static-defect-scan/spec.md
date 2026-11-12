# scenario-static-defect-scan Specification

## ADDED Requirements

### Requirement: 生产副作用规则族

静态扫描 SHALL 新增生产副作用规则族（表驱动，与既有规则同构挂载）：R1 改状态 click×位置选择器交叉判别（severity=high——click 目标含 `.first`/`nth()` 或缺少 `:has-text` 种子/fixture 作用域锚定，且场景描述或后续断言表明该 click 改变生产账本状态）；R2 网络守卫过宽（severity=medium——改状态 click 的 expect_network 守卫仅锚端点前缀，未收敛到可区分本次操作的记录级路径）；R3 批量破坏端点确认路径执行（severity=critical——点击目标指向确认弹窗破坏性主键且场景含批量端点（如 `POST /api/alerts/clear`、mark_all_handled 类）的 expect_network）；R4 全局聚合量绝对值断言（severity=medium——text_match 对全局聚合计数元素（如 `.ant-badge-count`）断言 exact/contains 具体数值）；R5 `<tag>:text-matches` 组件按钮锚定（severity=medium——CSS 标签前缀 + `:text-matches` 伪类组合，命中最小元素语义结构性失配，与既有双汉字规则同源不同形）。规则命中仅情报输出（fail-open 既有语义不变），规则族实现知识红线（`spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md`）的机械子集，MUST NOT 改变既有 4 规则行为。

#### Scenario: R1 位置点击改状态命中

- **WHEN** 场景含 `click` 步骤选择器 `button:has-text("标记已处理")` 且断言含 `expect_network`（无行级作用域锚定）
- **THEN** 扫描输出 R1 finding（high），情报注入 judge prompt

#### Scenario: R3 批量破坏确认路径命中

- **WHEN** 场景点击确认弹窗破坏性主键且守卫批量清理端点
- **THEN** 扫描输出 R3 finding（critical）

#### Scenario: 安全作用域写法不误报

- **WHEN** 改状态 click 已锚定种子行作用域（`.ant-list-item:has-text('[provfix-seed] …') button:has-text(…)`）且网络守卫收敛到记录级路径
- **THEN** R1/R2 不输出 finding

#### Scenario: 形态断言不误报

- **WHEN** 聚合计数元素断言为 regex 形态（`\d+`）而非具体数值
- **THEN** R4 不输出 finding

### Requirement: 存量场景集回扫入口

系统 SHALL 提供回扫 CLI 入口：对任意场景集目录（`test_scenarios.json` 集合）执行全规则族扫描并输出 findings 汇总（逐场景×逐规则×严重度），只读不改写；回扫报告供编写期修复与启用前误报审计。守卫测试 SHALL 以复刻真实事故形态的 fixtures（位置点击按钮、种子作用域改写版、批量破坏确认、聚合量绝对值、`<tag>:text-matches` 组合）双向锚定规则族（违规样本命中、合规样本零命中）。

#### Scenario: 回扫汇总输出

- **WHEN** 对含违规样本的场景集目录执行回扫 CLI
- **THEN** 输出逐场景×逐规则×严重度的 findings 汇总，不写任何场景文件

#### Scenario: fixtures 双向锚定

- **WHEN** 守卫测试运行
- **THEN** 事故形态 fixtures 逐规则命中断言通过，改写后合规 fixtures 全规则零命中断言通过
