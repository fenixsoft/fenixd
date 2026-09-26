## Why

架构图页签的 daemon 单体 `claude -p` 生成在 fenixd 与 fenix-desktop 两个项目实测全部 1800s 超时（进程组击杀），功能整体不可用。取证定案：bigmodel 网关对「大上下文 × 长输出」请求存在静默丢弃（TCP ESTAB、收发队列全零、转录零事件），而单体 spawn 形态把这类危险请求密集化——SKILL.md 全文（~30KB）内嵌首条 prompt、Explore 子代理取证报告（11KB+）全文回灌主 agent、主 agent 单轮生成完整候选 JSON。旁证：小上下文请求实测几十次零挂。

## What Changes

- 生成编排从单 Popen 改为顺序两阶段，磁盘为唯一交接面：
  - 阶段1 探索 run：小 prompt（~1KB，不注入 SKILL.md），只读取证写 `.fenix/architecture/evidence.md`，marker `ARCHIFY_EVIDENCE_DONE`；判定 `returncode==0` 且 evidence 非空。
  - 阶段2 出图 run：小 prompt（~2KB），SKILL.md 与 evidence 均以绝对路径引用（不内嵌全文），要求候选 JSON 分段小步写、禁单次巨量 Write；产物判定沿用现有 `_judge_artifact` 权威判定链不变。
- evidence.md 头部记录 repo HEAD sha + 时间戳；refresh 受理时 evidence 存在且 HEAD 一致则跳过阶段1（重试只付出图成本），HEAD 变化自动重探索。
- 总超时 1800s 拆为阶段1 ≤720s、阶段2 ≤1080s，进程组击杀范式沿用，error 文案区分阶段。
- `status.json` 增可选键 `stage`（`exploring` / `authoring` / null），向后兼容存量六键契约。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `project-architecture-diagram`: 生成机制从「单体 claude -p 一次完成取证+出图」改为「探索/出图两段式管线 + evidence 磁盘交接 + HEAD 指纹复用」；超时治理与状态字段相应扩展。

## Impact

- `core/dashboard/routes/architecture_routes.py`：prompt 构建拆分（探索/出图两个 builder）、`_run_generation` 两阶段编排、evidence HEAD 读写、超时拆分、status `stage` 键。
- `tests/test_dashboard_architecture_api.py`：spawn 假设类用例改造（fake spawn 按 prompt 内容区分阶段）+ 新增跳段/短路/分段超时用例。
- 不改动：vendored 零网络依赖原则、产物权威判定链、前端（`stage` 键后端先行向后兼容，前端细分文案后行）。
