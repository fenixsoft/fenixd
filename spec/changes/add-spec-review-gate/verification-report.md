# 验证报告：add-spec-review-gate

> ⚠️ 本报告由框架于 2026-09-13T13:56:05Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 21/23 场景通过，2 失败，0 错误（2 个真实产品 Bug）**

验证发现 1 个产品缺陷（CLI promote 路径绕过评审分流）和 1 个测试缺陷（提示词页签测试时序问题）。产品缺陷需优先修复，CLI 通道应消费 promote_drafted 返回的 next_status 执行正确的状态转移。

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 2 |
| 本链增量 Token（输入） | 11.60M |
| 本链增量 Token（输出） | 0.12M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match

- 关联场景：cli-promote-divergence-expose-bug
- 描述：CLI promote 命令对 full-track SPEC 执行晋升时，预期应转为 reviewing 状态（需人工评审），实际却直接转为 ready 状态，绕过评审分流
- 根因：cmd_promote 未消费 promote_drafted 返回的 next_status 字段，硬编码 transition 到 ready，CLI 通道与 API 通道晋升语义不一致
- 证据（场景 cli-promote-divergence-expose-bug 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "layer": 3, "stream": "stdout", "mode": "exact", "expected": "reviewing", "actual": "ready"}]
  - screenshots: []
  - first_failed_step: 步骤3: CLI promote 输出 ready 而非预期的 reviewing，cmd_promote 未传 config 直通 ready

### BUG-02（severity=minor）· test-defect

- 关联场景：web-prompts-page-spec-review-role
- 描述：测试场景时序问题：点击提示词菜单后立即尝试访问 Agent 切换器，PromptsPanel 异步加载 API 数据导致 Select 组件未渲染
- 根因：测试用例断言时序错置，未等待 PromptsPanel.data 加载完成
- 证据（场景 web-prompts-page-spec-review-role 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "layer": 1, "selector": "[data-testid=\"prompts-agent-switcher\"] .ant-select-selector", "expected": "可见并可交互", "actual": "Timeout 5000ms exceeded，元素不可见（PromptsPanel 异步加载 data，Select 组件未渲染）"}]
  - screenshots: []
  - first_failed_step: 步骤4: 点击 Agent 切换器超时，PromptsPanel.data 初始为 null，Select 组件在 API 返回前未渲染


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-fixtures | 向验证项目 /root/scheduling-showcase 写入 9 个夹具 SPEC（blocked 评审相关/冻结/熔断/ready/drafted）+ 复位 config.yaml：移除 gates.spec_review_mode、写入 agents.models.spec-review: []（供 AgentModelPanel 渲染 spec-review 角色卡片），供后续 CLI/API/Web 场景经 depends_on 串接消费。 | pass | 0/4 | - |
| cli-config-default-auto | 配置 getter 缺省值：ConfigLoader.get_spec_review_mode({}) 返回 auto（core/config.py:915-925）。 | pass | 0/2 | - |
| cli-skip-review-criteria | 评审跳过白名单判据全覆盖（spec-review-gate「评审跳过白名单」Requirement 6 个 Scenario）：should_skip_review 对 6+1 种构造形态批量判定——skip-ok（fast-track+0能力+2声明+非evo→跳过）、skip-evo（evo- 硬否决→不跳过）、skip-full（mode=full→不跳过）、skip-multicap（能力目录2→不跳过）、skip-nodecl（无声明段→保守不跳过）、skip-nomode（无 .spec.yaml→保守不跳过）、skip-never（config never 恒跳过）。 | pass | 0/8 | - |
| cli-config-explicit-never | 配置 getter 显式 never：get_spec_review_mode({'gates': {'spec_review_mode': 'never'}}) 返回 never。 | pass | 0/2 | - |
| cli-config-invalid-value-rejected | 配置校验拒绝非法枚举值：构造含 gates.spec_review_mode='always' 的 config dict，调用 _validate → 抛出 ValueError，消息含合法值 auto/never（core/config.py:366-371）。 | pass | 0/2 | - |
| cli-state-machine-transitions | 状态机 reviewing 转移边全覆盖（spec-review-gate「reviewing 状态与合法转移边」Requirement）：python3 直接调用 StateMachine transition 验证 6 条边：drafted→reviewing、reviewing→ready、reviewing→blocked、blocked→reviewing、reviewing→implementing（非法拒绝）、reviewing→verified（非法拒绝），以及 SpecStatus.ALL 含 reviewing 共 11 项。 | pass | 0/9 | - |
| cli-spec-review-prompt-file | 评审 Agent 提示词文件存在且含关键内容（spec-review-agent「评审 Agent 提示词文件注册」Requirement）：断言 agents/spec-review.md 文件存在、内容含三个评估维度 goal-fit/hole/regression、含 output 契约 status/findings/repairs。 | pass | 0/6 | - |
| cli-run-prefixes-registration | run_id 前缀双处登记（spec-review-agent「run_id 前缀双处登记」Scenario）：grep core/agent_runner/run_files.py 与 core/admin_monitor.py 的 _RUN_PREFIXES 常量，均含 'spec-review-'。 | pass | 0/4 | - |
| api-prompts-spec-review-agent | GET /api/prompts 返回 agents 数组含 spec-review 类型条目（spec-review-agent「评审 Agent 提示词文件注册」Scenario）：断言 200 + agents 数组长度≥9、agents[type=spec-review] 存在且 file=spec-review.md。 | pass | 0/4 | - |
| api-prompts-spec-review-content | spec-review 提示词内容含三维度关键字（spec-review-agent「三个评估维度」）：GET /api/prompts → agents[type=spec-review].content 含 goal-fit（或「方案评审」含中文）、hole、regression。 | pass | 0/4 | - |
| api-config-sources-includes-spec-review-mode | GET /api/config?project=fenixd 的 sources 键含 gates.spec_review_mode（data.py:3908-3909 受管键白名单已注册）：json_path sources 含该键。 | pass | 0/2 | - |
| api-config-read-side-missing-expose | 【暴露实现缺口】GET /api/config?project=fenixd 的 gates 段不含 spec_review_mode 字段：read_effective_config（data.py:4336-4350）未提取该受管键有效值，读侧回显缺失。断言 gates 键不含 spec_review_mode。 | pass | 0/3 | - |
| api-specs-list-regression | GET /api/specs 回归：fenixd 主项目与 scheduling-showcase 均返回 200 + specs 数组，既有端点不回归（core/dashboard/server.py:376-378）。 | pass | 0/3 | - |
| web-prompts-page-spec-review-role | 设置页提示词页签回归 + spec-review 角色可见：打开下拉后 Agent 列表含「Spec Review（方案评审）」选项（PromptsPanel.tsx:24 AGENT_LABELS 含 spec-review）。 | failed（已修正） | - | test-defect |
| web-overview-regression | 概览页回归（add-draft-promotion-gate 后回归点）：navigate #/overview，断言 ant-page-header 可见、标题含「跨项目概览」、无 console error。 | pass | 0/3 | - |
| cli-review-success-rejected | CLI review 成功路径（spec-review-gate「人工重新评审」Scenario）：对 spec-review-rejected: 的 blocked SPEC（verify-review-quickfix）执行 bin/fenix_cli.py review → 输出含「重新进入评审」、exit code 0、STATE.md 状态由 blocked 变为 reviewing。 | pass | 0/3 | - |
| cli-review-success-incomplete | CLI review 成功路径（spec-review-incomplete 前缀）：对 spec-review-incomplete: 的 blocked SPEC（verify-review-incomplete）执行 review → exit code 0、STATE.md 变为 reviewing。 | pass | 0/2 | - |
| cli-review-reject-noreview-blocked | CLI review 拒绝路径（spec-review-recovery「非评审 blocked 被拒」Scenario）：对熔断 blocked SPEC（verify-review-noreview，error 前缀非 spec-review-*）执行 review → exit code 非 0、输出含拒绝原因「未因评审进入 blocked」、STATE 保持 blocked。 | pass | 0/3 | - |
| cli-review-reject-frozen | CLI review 拒绝路径（spec-review-recovery「冻结态被拒」Scenario）：对 frozen:true 的 spec-review-rejected blocked SPEC（verify-review-frozen）执行 review → exit code 非 0、输出含「已冻结」、STATE 保持 blocked、frozen 字段未被清除。 | pass | 0/3 | - |
| cli-review-reject-not-blocked | CLI review 拒绝路径（spec-review-recovery「状态不符被拒」Scenario）：对 ready 状态 SPEC（verify-review-ready）执行 review → exit code 非 0、输出含「状态不是 blocked」、STATE 保持 ready。 | pass | 0/3 | - |
| cli-review-project-flag | CLI review --project 指定项目路径：在默认 cwd（fenixd 验证树，非项目根）执行 --project /root/scheduling-showcase review → 作用于 scheduling-showcase 的 STATE.md、exit code 0。（原 cwd=/tmp 下相对路径 bin/fenix_cli.py 无法解析，exit 2） | pass | 0/2 | - |
| cli-promote-divergence-expose-bug | 【暴露实现缺口】CLI promote 对非 fast-track SPEC（full-track）执行 promote：预期 next_status=reviewing（不跳过评审），实际因 cmd_promote 未传 config 直通 ready。退出码 0 但 STATE 状态为 ready 而非 reviewing，暴露 CLI promote 通道绕过评审分流的缺陷。 | failed | 1/2 | product-bug |
| web-agent-model-panel-spec-review-card | 模型分配面板 spec-review 角色卡片可见（AgentModelPanel.tsx:175 Card title=role.label）：项目级作用域下（cli-seed-fixtures 写入 agents.models.spec-review: []）模型分配面板渲染 spec-review 角色卡片。 | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-prompts-page-spec-review-role | no_click_interception [data-testid="prompts-agent-switcher"] .ant-select-selector 点击 | test-defect | 测试用例自身缺陷（非产品缺陷） | 元素存在（div[data-testid=prompts-agent-switcher]）但内部 Ant Design Select 组件因异步加载未渲染，选择器层级问题导致无法交互 |

## 本轮场景集变更

场景集与持久化集一致，无变更。

