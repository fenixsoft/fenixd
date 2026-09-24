# code-fix-startup-stage-visibility 规范

## ADDED Requirements

### Requirement: 准备期启动阶段显示

code-fix 批处于 `fixing` 或 `retrying` 阶段且 out 产物（`fix-out-<run_id>.jsonl`）
零有效行时，进度数据 MUST 包含非空 `startup_stage` 字段，向用户呈现 agent
当前所处启动阶段。

#### Scenario: run 转录文件存在

- **WHEN** 批 `running=true`、`phase ∈ {fixing, retrying}`、out 零有效行，
  且 `.fenix/runs/<run_id>.jsonl` 存在
- **THEN** `startup_stage` 为非空对象，含阶段短语与自转录文件创建时刻起的
  已等待分钟数
- **AND** 阶段短语按末行事件类型映射：会话初始化事件（hook/init 类）→
  会话初始化；assistant 文本/thinking → 模型分析分组；assistant 工具调用 →
  正在执行该工具

#### Scenario: run 转录文件缺失

- **WHEN** 上述条件成立但转录文件不存在（进程尚未创建文件）
- **THEN** `startup_stage` 仍为非空对象，阶段短语为「等待 agent 进程启动」，
  已等待时长缺省不显示

### Requirement: 处置开始后收敛

首条有效处置行落盘后，准备期显示 MUST 让位于条级计数。

#### Scenario: out 出现有效行

- **WHEN** out 产物存在至少一行有效处置记录
- **THEN** `startup_stage` 为 null，`item_done` 按既有合成口径照常返回

### Requirement: 读侧容错

启动阶段推断为尽力而为语义，任何异常 MUST NOT 影响主进度返回。

#### Scenario: 转录文件损坏或不可解析

- **WHEN** 转录文件读取失败、末行为空或不可解析为 JSON、或含未知事件形态
- **THEN** `startup_stage` 置 null（MUST NOT 抛异常、MUST NOT 500、
  MUST NOT 伪造阶段文案）

### Requirement: 前端准备段渲染

进度卡对 `item_done=null` 的渲染行为按 `startup_stage` 是否在场二分。

#### Scenario: 准备段显示

- **WHEN** `item_done=null` 且 `startup_stage` 非空
- **THEN** 进度卡渲染准备段（阶段短语 + 已等待时长），替代原「整段不渲染」

#### Scenario: 维持既有空白口径

- **WHEN** `item_done=null` 且 `startup_stage` 为 null
- **THEN** 维持 2026-09-23 口径整段不渲染（不显示误导性 0 计数）
