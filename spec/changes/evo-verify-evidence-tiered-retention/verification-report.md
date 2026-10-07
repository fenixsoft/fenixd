# 验证报告：evo-verify-evidence-tiered-retention

> ⚠️ 本报告由框架于 2026-10-07T20:04:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T20:04:15.623282+00:00+run-result@mtime1791403455657405068

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.34M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| retention-template-declares-tiering | 契约模板 evidence_dir 注释块后新增分级留存声明段（tasks 1.1；出处 core/verify_contract_template.yaml:152-158）：注释化字段 evidence_retention/max_binary_bytes 在案、缺省 10485760、分级规则注释（sha256 sidecar + 复现命令 + 存放路径登记；文本/JSON/哈希/小日志直接入库）在场，且模板缺省形态保持未声明（无未注释的 evidence_retention: 行） | pass | 0/6 | - |
| retention-template-uncommented-load | 按模板形态取消注释声明（evidence_retention.max_binary_bytes: 10485760）后写入项目 .fenix/verify.yaml，load_verify_contract 加载成功且解析值为声明值（tasks 1.1 验收「取消注释后按声明值加载」；出处 core/verify_contract_template.yaml:156-157、tests/test_verify_evidence_placement.py:262-278 同款 patched 加载） | pass | 0/2 | - |
| retention-parse-declared-value-wins | 契约声明 evidence_retention.max_binary_bytes 为合法正整数（1048577）→ 解析结果 evidence_max_binary_bytes 取声明值（spec Acceptance Scenario 1；出处 core/verify_contract.py:550-557、tests/test_verify_contract.py:112-124） | pass | 0/2 | - |
| retention-parse-illegal-fallback | 契约声明非法值（负数 -5、非整数 abc/10mb、bool true、整段非映射字符串与非映射 list、0）→ 全部经 _positive_int_or_default 静默回退缺省 10485760，契约加载不报错不阻断（spec Acceptance Scenario 2；出处 core/verify_contract.py:171-188、550-557） | pass | 0/5 | - |
| retention-parse-absent-default | 契约存在但未声明 evidence_retention → 解析结果为缺省 10485760；且 VerifyContract() 空构造的 dataclass 缺省独立同为 10485760（spec Acceptance Scenario 3；出处 core/verify_contract.py:165、281、tests/test_verify_contract.py:146-151） | pass | 0/4 | - |
| retention-prompt-declared-threshold-clause | 契约声明自定义阈值（max_binary_bytes: 2048）→ PromptBuilder._evidence_placement_section 渲染的落位指引包含分级条款（分级留存 / sha256 sidecar / MUST NOT 入 git），且阈值按声明值渲染为「2048 字节」（_fmt_bytes 非 1MB 整数倍走字节形态）（spec Acceptance Scenario 4；出处 core/agent_runner/prompt_builder.py:1035-1095） | pass | 0/5 | - |
| retention-prompt-default-threshold-clause | 契约存在但未声明阈值（走缺省 10MB）→ 落位指引同样包含分级条款，阈值渲染为 10MB（spec Acceptance Scenario 5；出处 core/agent_runner/prompt_builder.py:1049-1050、1072、tests/test_verify_evidence_placement.py:562-575） | pass | 0/4 | - |
| retention-prompt-failopen-contract-missing | 项目无 .fenix/verify.yaml（契约整体缺失）→ 落位指引软约束 fail-open：分级条款照常渲染且阈值取缺省 10MB，派发不因软约束失败中止（出处 core/agent_runner/prompt_builder.py:1059-1066 的最终兜底分支） | pass | 0/4 | - |
| retention-end-to-end-template-to-prompt | 跨层联动回归：从模板文本出发模拟项目声明（取消注释并把阈值改为 2097152 即 2MB）→ 写入临时项目 .fenix/verify.yaml → load_verify_contract 解析出 2097152 → _evidence_placement_section 渲染含分级条款且阈值渲染为 2MB——契约声明逐层驱动落位指引（spec 目标 1+2 串接；出处 core/verify_contract_template.yaml:155-157 → core/verify_contract.py:550-557 → core/agent_runner/prompt_builder.py:1046、1072、1088-1092） | pass | 0/4 | - |
| retention-tests-contract-three-states | 解析三态测试套件在案且通过（tasks 3.1）：pytest -k TestEvidenceRetentionContract 跑 tests/test_verify_contract.py，三个用例（test_declared_value_wins / test_illegal_values_silently_fall_back_to_default / test_absent_section_falls_back_to_default）全部 PASSED、退出码 0（出处 tests/test_verify_contract.py:105-152，unittest 类无 parametrize 无后缀） | pass | 0/5 | - |
| retention-tests-placement-clause-rendering | 落位指引分级条款测试套件在案且通过（tasks 3.2）：pytest -v -k 表达式跑 tests/test_verify_evidence_placement.py，覆盖 test_template_declares_evidence_retention_tiering、test_retention_clause_rendered_with_declared_threshold、test_retention_clause_rendered_with_default_threshold、test_retention_clause_survives_contract_load_failure、test_injection_wiring_covers_impl_and_verify_lanes 全部 PASSED、退出码 0（-k 的 template_declares 词干同时命中相邻用例 test_template_declares_evidence_dir_in_comments，实测选中 6 用例、末行 6 passed，断言按实测形态落盘；出处 tests/test_verify_evidence_placement.py:245、546、562、576、589） | pass | 0/7 | - |
