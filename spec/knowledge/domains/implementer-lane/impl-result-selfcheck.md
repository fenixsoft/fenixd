<!-- knowledge: capability=impl-result-selfcheck rev=1 sources=spec/archive/2026-09-27-add-impl-selfcheck-model-probe -->

# 实现结果文件收工自检

agent 收工前对结果文件的自证通道：与 daemon 侧硬门同源的零网络 CLI，让契约类失败在 run 内修复而非整轮重派。

## 现行规则

- 自检 CLI：`core/agent_runner.result_gate` 模块提供 `python3 -m core.agent_runner.result_gate --selfcheck <结果文件路径>` 入口，在 worktree 内、无 daemon、无网络依赖下对结果文件执行与 daemon 侧收工硬门**同源**的校验（直接调用同一校验函数对象，不复制校验逻辑）。退出码 0=PASS、1=FAIL；FAIL 时逐条输出违规明细（含字段路径与期望形态）到 stderr；缺失参数、文件不存在等使用错误输出用法提示并以非零码退出。daemon 侧既有硬门判定逻辑保持不变（本能力只加出口，不改判定）。
- 同源性约束：同一结果文件分别过自检 CLI 与 daemon 硬门，判定一致（自检 PASS 则硬门不因结果文件形状拒收）。
- 零副作用：自检通过时除读取目标文件外不产生任何文件写入或网络请求。
- 收尾 prompt 注入：implementer 收尾检查注入段（`prompt_builder.py`）包含——①自检 CLI 的完整调用命令与「非零退出不得收工、按 stderr 明细修复后重跑至退出码 0」的强制措辞；②dispositions 合法形态正例 `[{"disposition": "fixed"}, {"disposition": "deferred", "reason": "<非空理由>"}]` 与非法形态反例 `["fixed", "fixed"]` 的逐字对照；③`status` 枚举与必填键的固化说明。正反例与 result_gate 校验体的实际判据一致（以校验体为单源）。
- 静态模板与动态注入分工：`agents/implementer.md` 静态模板可含通用自检原则，动态契约细节（键名/正反例）必须经 prompt 注入下发，不得在静态模板中另写一份可能与校验体漂移的细节。

## 溯源

- 2026-09-27 2026-09-27-add-impl-selfcheck-model-probe — 建立 `--selfcheck` 零网络 CLI（复用生产校验体）与收尾 prompt 注入契约（命令、正反例、枚举说明）
