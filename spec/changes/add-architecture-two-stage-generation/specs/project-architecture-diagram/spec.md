## MODIFIED Requirements

### Requirement: 刷新按钮触发一次性 headless claude（archify）生成

生成机制改为两段式管线：阶段1 探索 run 与阶段2 出图 run 顺序执行，磁盘（`.fenix/architecture/evidence.md`）为唯一交接面；两段 prompt 均不内嵌 vendored SKILL.md 全文（以包根绝对路径引用）。

#### Scenario: 两阶段顺序执行
- **WHEN** refresh 受理且 evidence.md 不存在或 HEAD 指纹不一致
- **THEN** 先 spawn 阶段1 探索 run（prompt 含 `ARCHIFY_EVIDENCE_DONE` marker 契约与 evidence.md 写盘绝对路径，不含 archify SKILL.md 全文）；evidence.md 落盘且非空后再 spawn 阶段2 出图 run（prompt 以绝对路径引用 SKILL.md 与 evidence.md，不内嵌全文）

#### Scenario: 阶段1 判定链
- **WHEN** 阶段1 进程退出
- **THEN** `returncode==0` 且 evidence.md 存在且非空才进入阶段2；任一不满足则直接 failed，不 spawn 阶段2

#### Scenario: 阶段2 产物判定不变
- **WHEN** 阶段2 进程退出
- **THEN** 沿用现有权威判定链（`ARCHIFY_DONE <组件数>` marker + 自包含 HTML 硬门 + 组件数 8–16），判定行为与改造前一致

#### Scenario: 候选 JSON 分段小步写纪律
- **WHEN** 阶段2 prompt 构建
- **THEN** prompt 显式要求候选 JSON 先写骨架再逐段 Edit 补全（分段小步写盘），禁止单次巨量 Write

### Requirement: 生成生命周期治理（单飞 / 超时 / 重启残留 / 前端轮询）

超时治理按阶段拆分；`status.json` 增加可选 `stage` 键。

#### Scenario: 分段超时
- **WHEN** 阶段1 运行超过 720s 或阶段2 运行超过 1080s
- **THEN** 对该段进程组执行 SIGKILL 击杀（既有范式），status.json `state=failed`，error 文案注明所属阶段（「阶段1 探索超时」/「阶段2 出图超时」）

#### Scenario: stage 字段写入
- **WHEN** 生成线程处于阶段1 或阶段2 运行中
- **THEN** status.json 写入 `stage` 为 `"exploring"` / `"authoring"`；终态时该键置 null；存量六键字段语义不变（向后兼容）

## ADDED Requirements

### Requirement: evidence 取证复用与 HEAD 指纹失效

evidence.md 头部记录生成时的 repo HEAD sha 与时间戳；refresh 受理时按 HEAD 指纹决定是否跳过阶段1。

#### Scenario: HEAD 一致跳过探索
- **WHEN** refresh 受理时 evidence.md 存在且其记录的 HEAD sha 与当前 repo HEAD 一致
- **THEN** 跳过阶段1 直接进入阶段2（重试只付出图成本）

#### Scenario: HEAD 变化自动重探索
- **WHEN** refresh 受理时 evidence.md 不存在、损坏、或其记录的 HEAD sha 与当前 repo HEAD 不一致
- **THEN** 正常执行阶段1 重新取证（图不因复用而陈旧）
