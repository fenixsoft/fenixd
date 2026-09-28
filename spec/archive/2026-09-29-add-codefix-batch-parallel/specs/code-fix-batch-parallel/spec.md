# code-fix-batch-parallel 能力规格

code-fix 批内按文件组并行处置协议：orchestrator 派子代理并行修复、汇总落盘、一次验证一次提交；框架契约（单 run/单 out_path/回归+合回）零改动。

## ADDED Requirements

### Requirement: 批内并行处置协议

批含 ≥2 个文件组且条目 >2 时，orchestrator MUST 以文件组为粒度派子代理并行处置：同波并发子代理 ≤3，完成一组回收并补派下一组。子代理 prompt MUST 携带该组条目 JSON 与修复契约（最小改动、fenix-ignore 标记规则、out 行格式）；子代理 MUST NOT 自行写 `{out_path}`、自行验证、自行提交。

#### Scenario: 多组批并行处置
- **WHEN** 一批含 ≥2 个文件组（如 20 条拆 6 组）
- **THEN** orchestrator 以 ≤3 并发波次派子代理；全部组完成后每条目都有 out 记录、worktree 内改动完整、单次提交包含全批 item_id

#### Scenario: 单组批退化为串行
- **WHEN** 一批仅 1 个文件组或条目 ≤2
- **THEN** orchestrator 不派子代理，按串行路径直接处置（行为与现状一致）

### Requirement: 组级增量落盘与单写者

每组子代理返回后，orchestrator MUST 立即校验（每行含 `item_id` 与 `status`）并追加写该组全部 out 行到 `{out_path}`；`{out_path}` 的唯一写者是 orchestrator。MUST NOT 攒到全部组完成才写。

#### Scenario: 条级进度随组可见
- **WHEN** 批内 3 组中第 1 组完成
- **THEN** `{out_path}` 已含第 1 组全部行，条级进度合成（item_done/current_item）在 run 在飞期间可读到该组条目（读侧零改动即兼容）

#### Scenario: 非法产物行兜底
- **WHEN** 某子代理返回的记录缺 `item_id` 或 `status`
- **THEN** orchestrator 对该组重试一次处置；重试后仍非法的条目按未处置标注 skipped，不写非法行

### Requirement: 子代理失败兜底

子代理失败/超时/产物不可解析时，orchestrator MUST 亲自重做该组；重做仍失败按既有 skipped 语义标注（unfixable/needs_human）。任何单组兜底 MUST NOT 阻塞其他组的落盘与派发。

#### Scenario: 子代理失败重做
- **WHEN** 某组子代理报错或超时无产物
- **THEN** orchestrator 串行重做该组并正常落行；其他组结果不受影响照常落盘

### Requirement: 汇总后一次验证一次提交

全部组落盘完成后，orchestrator MUST 按触碰面做**一次**定向验证（仅前端→tsc+前端单测；仅 Python→定向 pytest；混合→两者），然后单次提交全批改动。MUST NOT 逐组验证、MUST NOT 多次提交。

#### Scenario: 验证提交契约不变
- **WHEN** 并行批全部组落盘完成
- **THEN** 恰好一次验证、一次 commit（提交信息含全批 item_id），随后框架回归+合回流程与现状完全一致
