# impl-result-selfcheck 能力增量（add-impl-selfcheck-model-probe）

> 结果文件收工自证契约：result_gate 生产校验体暴露为零网络 CLI，agent 收工前自检，契约类失败在 run 内修复而非整轮重派。

## ADDED Requirements

### Requirement: 收工自证 CLI（复用生产校验体）

`core/agent_runner.result_gate` 模块 MUST 提供 `python3 -m core.agent_runner.result_gate --selfcheck <结果文件路径>` CLI 入口：在 worktree 内、无 daemon、无网络依赖下对指定结果文件执行与 daemon 侧收工硬门相同源的校验（直接调用同一校验函数对象，MUST NOT 复制校验逻辑）；退出码 0=PASS、1=FAIL，FAIL 时逐条输出违规明细（含字段路径与期望形态）到 stderr。CLI 对缺失参数、文件不存在等使用错误 MUST 输出用法提示并以非零码退出。daemon 侧既有硬门判定逻辑 MUST 保持不变（本能力只加出口，不改判定）。

#### Scenario: 字符串数组 dispositions 被自检拦截

- **WHEN** agent 写出 `code_review.dispositions: ["fixed", "fixed"]`（字符串数组）后运行自检 CLI
- **THEN** 退出码为 1，stderr 指明 dispositions 逐条须为对象（含 `disposition` 键）及违规条目序号；agent 据此在 run 内改写为 `[{"disposition": "fixed"}, ...]` 后重跑自检得到退出码 0

#### Scenario: 自检通过零副作用

- **WHEN** 结果文件完全合法时运行自检 CLI
- **THEN** 退出码 0、stderr 无违规明细，除读取目标文件外不产生任何文件写入或网络请求

#### Scenario: 自检与 daemon 硬门同源

- **WHEN** 同一结果文件分别过自检 CLI 与 daemon 侧收工硬门校验
- **THEN** 两者判定一致（自检 PASS 则硬门不因结果文件形状拒收）；daemon 硬门校验函数被自检 CLI 复用而非复制（实现以同函数对象调用为准）

### Requirement: 收尾 prompt 注入自检要求与正反例

implementer 收尾检查注入段（`prompt_builder.py`）MUST 包含：①自检 CLI 的完整调用命令与「非零退出不得收工、按 stderr 明细修复后重跑至退出码 0」的强制措辞；②dispositions 合法形态正例 `[{"disposition": "fixed"}, {"disposition": "deferred", "reason": "<非空理由>"}]` 与非法形态反例 `["fixed", "fixed"]` 的逐字对照；③`status` 枚举与必填键的固化说明。正反例 MUST 与 result_gate 校验体的实际判据一致（以校验体为单源）。`agents/implementer.md` 静态模板可包含通用自检原则，但动态契约细节（键名/正反例）MUST 经 prompt 注入下发，MUST NOT 在静态模板中另写一份可能与校验体漂移的细节。

#### Scenario: 收尾注入含可执行命令

- **WHEN** 框架为某 impl run 构建收尾检查 prompt 段
- **THEN** 该段包含 `python3 -m core.agent_runner.result_gate --selfcheck` 的完整命令、正反例 JSON 片段、以及非零退出不得收工的强制措辞
