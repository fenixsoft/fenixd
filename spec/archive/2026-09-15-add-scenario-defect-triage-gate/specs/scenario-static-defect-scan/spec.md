# scenario-static-defect-scan

场景集静态缺陷扫描：模式表驱动的纯 Python 扫描器，在场景执行前检出「结构合法但内容必败」的已知缺陷模式，产出结构化情报供 judge 定向修复。只做情报、不拦截执行。

## ADDED Requirements

### Requirement: 模式表驱动的静态扫描

系统 SHALL 在每轮验证的场景执行前（`_apply_scenario_freeze` 完成后）对生效场景集（test_scenarios.json）执行静态缺陷扫描。扫描器 SHALL 以模式表驱动，初始模式表 SHALL 包含：

1. **跨轮字面端口残留**（cli/api 场景）：场景 steps 的 `command`/`stdin` 文本中出现字面端口号（`http://127.0.0.1:<N>` 形式或 `:<N>` 端口字面量），且 `<N>` ≠ 本轮 serving 实例端口 → 报「跨轮端口残留：运行时 MUST 引用 FENIX_VERIFY_PORT / FENIX_VERIFY_BASE_URL 环境变量」。
2. **跨轮 navigate URL 残留**（web 场景）：`navigate` 步骤 value 中 URL 的字面端口 ≠ 本轮 serving 端口 → 报「跨轮残留 URL：执行时引擎以契约 base_url 为准，但情报须提示 judge 该场景入口指向已失效端口」。
3. **双汉字文本选择器**（web 场景）：steps `target` 或断言中出现恰好 2 个汉字的文本匹配（如 `getByText('确定')`、`hasText="提交"`）→ 报「antd Button autoInsertSpace：双汉字文本渲染为『X X』，建议改用 getByRole(name) 或含空格变体」。

模式表 SHALL 为可扩展的数据结构（新增模式不改扫描器主体）；每条 finding SHALL 包含 `scenario_id`、`rule_id`、`location`（场景内定位信息）、`message`（缺陷说明与修复方向）。

#### Scenario: 检出跨轮端口残留

- **WHEN** 本轮 serving 端口为 41200，场景 cli-seed-X 的 stdin 代码含 `http://127.0.0.1:57905/api/projects`
- **THEN** 扫描产出 finding：`scenario_id=cli-seed-X`、`rule_id=stale_literal_port`、message 指引改用 FENIX_VERIFY_PORT

#### Scenario: 端口一致不误报

- **WHEN** 场景文本中的字面端口与本轮 serving 端口相同
- **THEN** 该模式不产出 finding（不报「脆弱绑定」类低价值情报）

#### Scenario: 检出双汉字文本选择器

- **WHEN** web 场景断言含 `getByText('确定')`
- **THEN** 扫描产出 finding：rule_id=double_han_text_selector，message 说明 antd autoInsertSpace 渲染行为与替代写法

### Requirement: findings 落盘与 judge 情报注入

扫描产出的 findings SHALL 结构化落盘至 `.fenix/verify-progress/<spec>/scenario_static_findings.json`（每轮覆盖写），且 SHALL 在 judge（planner-judge）prompt 构建时注入定向情报段，段内 MUST 声明：检出场景的缺陷修复属 judge 职责（原地修复协议、申报 scenario-repaired），judge 对已检出场景 MUST 先修复已知缺陷再裁决。findings 为空时 MUST NOT 注入该段（prompt 与无扫描时保持可一致）。

#### Scenario: 情报段注入

- **WHEN** 扫描产出 ≥1 条 finding 且 judge 被派发
- **THEN** judge prompt 含静态情报段，逐条列出 scenario_id 与缺陷说明及修复职责声明

#### Scenario: 零 finding 不注入

- **WHEN** 扫描产出 0 条 finding
- **THEN** judge prompt 不含静态情报段

### Requirement: fail-open 扫描边界

静态扫描属辅助情报，扫描器任何异常（场景文件读取失败、模式匹配异常、serving 端口未知等）SHALL 记 WARNING 后跳过本轮扫描，MUST NOT 阻断验证流程、MUST NOT 产生 error 终态。serving 端口未知的轮次，端口比对类模式 SHALL 整体跳过（双汉字等纯文本模式仍可执行）。

#### Scenario: 扫描异常不阻断验证

- **WHEN** 扫描器在读场景文件时抛出异常
- **THEN** 框架记 WARNING 留痕，验证流程继续正常执行（场景照跑、judge 照常派发）
