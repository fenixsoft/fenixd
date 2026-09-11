# verdict-visibility 增量规格

## ADDED Requirements

### Requirement: 被裁决过滤失败场景的摘要展示

Dashboard SPEC 详情页「Bug 列表」页签 MUST 展示被分类过滤（classification ∈
test-defect/flaky/env，即非 product-bug）的失败/错误场景摘要，使用户在
「有失败+有失败截图+无产品 Bug」时能看到裁决结论与理由。摘要 MUST 包含：
场景 id、分类标签、裁决理由/证据摘要（evidence 或 status_corrected 标注）、
关联截图缩略图（有则显示）。无任何失败场景时空态文案为「无遗留 Bug」。

#### Scenario: 有被过滤失败时展示裁决摘要
- **WHEN** report.json 存在 status 为 failed 的场景且其 classification 为
  test-defect，而 Bug 列表（parse_bugs）因此为空
- **THEN** Bug 列表页签显示被过滤场景的摘要条目（含场景 id、分类标签
  「测试缺陷」、裁决证据），而非仅显示「无遗留 Bug」

#### Scenario: 摘要含失败截图
- **WHEN** 被过滤失败场景的 screenshots 字段非空
- **THEN** 摘要条目渲染该场景的截图缩略图（复用现有 /screenshots/ 路由，
  点击可放大）

#### Scenario: 无失败场景时保持原空态
- **WHEN** report.json 全部场景通过或不存在失败场景
- **THEN** Bug 列表页签显示「无遗留 Bug」空态，不渲染摘要区块

### Requirement: 后端 filtered_failures 结构

`spec_detail` 响应 MUST 新增 `filtered_failures` 字段：从 report.json 的
scenarios 提取 status ∈ (fail, failed, error) 且 classification ∈ 非
product-bug 分类的场景，每项含 scenario_id、classification、evidence 摘要、
screenshots（basename 归一化）、status_corrected。旧格式 report.json
（无 classification 字段）不产生 filtered_failures 条目（fail-open 语义与
parse_bugs 收录规则互补，向后兼容）。

#### Scenario: test-defect 失败场景进入 filtered_failures
- **WHEN** report.json 某场景 status=failed 且 classification=test-defect
- **THEN** /api/specs/&lt;name&gt; 响应的 filtered_failures 含该场景
  （scenario_id、classification=test-defect、screenshots 为文件名列表）

#### Scenario: 旧格式数据不产生条目
- **WHEN** report.json 某场景 status=failed 且无 classification 字段
- **THEN** 该场景不进入 filtered_failures（它按既有规则已收录进 bugs）
