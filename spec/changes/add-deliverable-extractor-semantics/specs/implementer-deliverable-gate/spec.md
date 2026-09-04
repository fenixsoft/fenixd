# implementer-deliverable-gate 增量规格（提取器语义升级）

## MODIFIED Requirements

### Requirement: 交付物路径提取
系统从 SPEC 的 tasks.md 与 proposal.md 提取路径时 MUST 输出结构化两类：`deliverables`（新建交付物，参与缺件判定）与 `references`（既有文件引用，不参与缺件判定）。分类规则：路径位于「新增/创建/添加/新增 core|tests|.fenix|scripts 前缀文件」等交付语境（tasks 勾选行、 proposal 的 Capabilities/交付清单）时归为 deliverables；位于「实现依据/挂钩点/插入点/真实夹具/上游依赖」等引用语境（tasks 头部说明段）时归为 references；语境无法判定时保守归为 deliverables。原 `extract_paths` 平面列表行为由 `extract_paths_typed` 取代（保留旧函数签名做兼容包装）。

#### Scenario: 引用语境不阻断
- **GIVEN** tasks.md「实现依据」段引用 `.fenix/core/agent_runner.py` 等 4 个既有框架文件，实现分支中这些文件以 `.fenix` 符号链接形式无法按树查找
- **WHEN** 交付物守卫校验
- **THEN** 4 个引用路径归入 references，不产生缺件
- **AND** 不阻断 merge、不消耗重派计数

#### Scenario: 交付语境仍阻断
- **GIVEN** tasks 勾选行声明新建某个 core 下源文件而分支中不存在
- **WHEN** 守卫校验
- **THEN** 缺件判定照常阻断（既有行为不变）

### Requirement: .fenix 前缀归一化（正式化）
对参与校验的任一路径，若以 `.fenix/` 前缀开头 MUST 以去除前缀后的根路径在分支中复检（自引用符号链接语义）；复检通过视为存在。该行为此前以热修 4461231 落地但无测试覆盖，本变更补齐单元测试并以 add-interaction-contract-and-per-assert-triage 真实分支为回归夹具。

#### Scenario: 归一化复检回归
- **GIVEN** 分支 `fenix/add-interaction-contract-and-per-assert-triage-1788091910`（真实夹具）
- **WHEN** 校验 `.fenix/core/agent_runner.py`
- **THEN** 归一化为 `core/agent_runner.py` 后判定存在（复现热修行为）

### Requirement: 引用类软校验
references 类路径在分支中不存在时 MUST 仅记录审计日志（含 spec 与路径清单），MUST NOT 产生缺件、重派或状态变更。

#### Scenario: 引用缺失仅留痕
- **WHEN** 某 references 路径在分支中不存在（如文档引用了将被重命名的文件）
- **THEN** 审计日志记录该路径，守卫放行
