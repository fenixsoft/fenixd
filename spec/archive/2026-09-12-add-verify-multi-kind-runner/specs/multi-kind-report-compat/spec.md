# multi-kind-report-compat — 报告、裁决与冻结集兼容

## ADDED Requirements

### Requirement: report.json kind 透传

验证报告 scenarios 列表每个元素 SHALL 携带 `kind` 字段（透传场景定义）；`summary` 统计口径不变（blocked-env 仍计入 warning）。CLI/API 场景元素的 `screenshots` 与 `visual_results` MUST 为空列表（schema 兼容，旧读侧读到空值不报错）。

#### Scenario: 报告元素携带 kind
- **WHEN** 混合场景集验证完成生成 report.json
- **THEN** 每个 scenario 元素含正确 `kind`；旧版读侧（仅读 status/summary 的路径）行为不变

#### Scenario: 空截图列表合法
- **WHEN** cli 场景结果进入报告
- **THEN** `screenshots` 为空列表、`visual_results` 为空列表，报告渲染不报错

### Requirement: Dashboard 字段驱动渲染

dashboard spec detail 场景页签 SHALL 增加 kind 徽章（web/cli/api 视觉区分）；断言详情渲染 MUST 按字段有无自适应（有 `selector` 显示选择器；cli 的 `stream`/`exit_code`、api 的 `path`/`status` 各自随字段渲染），MUST NOT 按 kind 写分支组件；截图区对空列表显示占位说明（CLI/API 场景证据为命令输出/HTTP 响应体）。

#### Scenario: CLI 断言详情渲染
- **WHEN** 查看某 cli 场景的断言详情
- **THEN** 显示 exit_code 期望/实际、输出匹配 mode 与命中片段等实际存在字段，无 selector 列残留

#### Scenario: 截图占位
- **WHEN** api 场景详情页无截图
- **THEN** 截图区显示占位说明而非空白或报错

### Requirement: verdict 链零改动回归

裁决链（`core/verdict_check.py`）的逐断言归因（assertion_triage 四分类）、product-bug 拦截豁免、证据合规检查 MUST 对 CLI/API 断言照常工作——它们只依赖 `assertion_results` 的 `pass`/`layer`/`classification` 字段与 `failed_assertions` 非空，不依赖 DOM 语义。合入前 MUST 以 CLI/API 夹具回归验证以下不变量：非 PASS 场景缺 triage 判违规；全失败断言非 product-bug 才可豁免；单条 product-bug 断言阻止场景级豁免。

#### Scenario: API 失败断言逐条归因
- **WHEN** api 场景 `status_code` 断言失败且 report 未附 assertion_triage
- **THEN** 裁决链判「逐断言归因违规」，与 web 场景同规则

#### Scenario: CLI product-bug 派生 fix 链
- **WHEN** cli 场景 `output_match` 失败被 triage 归类 product-bug 并附证据
- **THEN** 裁决产出 bug-found，进入既有修复循环（与 web 失败同路径）

### Requirement: 场景冻结 kind 携带

场景冻结条目（`ScenarioEntry`）SHALL 增加可选 `kind` 字段：`to_dict` 序列化、读侧缺失时缺省 `web`；存量冻结文件零迁移。冻结集补齐/合并场景 MUST 携带 kind，使补齐后的场景可被正确 Runner 执行。

#### Scenario: 存量冻结文件零迁移
- **WHEN** 读取不含 kind 的存量 scenarios.json 并走 diff 校验
- **THEN** 条目按 web 处理，diff 逻辑与写回内容兼容（新增 kind 字段可选）

#### Scenario: 冻结条目携带 kind
- **WHEN** 混合场景集首轮冻结写回 scenarios.json
- **THEN** 每个条目含其 kind，后续轮次读回的 kind 与场景集一致
