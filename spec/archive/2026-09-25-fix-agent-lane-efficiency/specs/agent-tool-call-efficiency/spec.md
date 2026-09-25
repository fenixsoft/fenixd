# agent-tool-call-efficiency — 工具调用效率与取证深度（新增）

## ADDED Requirements

### Requirement: 长车道提示词注入工具调用效率契约段

实现者（`implementer` / `fast-track`）与评审（`spec-review`）车道的 prompt SHALL 注入一段「工具调用效率」契约文本，要求：

1. **批量并行**：同一轮内相互独立、无数据依赖的工具调用（多个读取/检索）MUST 合并为一个批次一次性提交，MUST NOT 逐个串行提交；
2. **定向读取**：定位代码或内容 MUST 优先用 `Grep` / 带范围参数的 `Read`，MUST NOT 对未发生变更的大文件反复整文件读取；
3. **同 run 去重**：同一 run 内已读取且未变更的文件 MUST NOT 重复整文件读取（需复核时用范围读或检索）。

该段为**规范性提示词文本**，MUST NOT 引入框架侧工具拦截或对流式处理时序的改动。段注入位置 MUST 不破坏既有的契约段顺序断言测试。

#### Scenario: 双实现车道均注入效率段
- **WHEN** 构建 `implementer` 与 `fast-track` 车道的 prompt
- **THEN** 两者均含「工具调用效率」契约段，且段内含批量并行、定向读取、同 run 去重三条要求

#### Scenario: 评审车道注入效率段
- **WHEN** 构建 `spec-review` 车道 prompt
- **THEN** 含同一效率契约段

#### Scenario: 不改变流式处理行为
- **WHEN** run 运行期间发生工具调用
- **THEN** 工具调用的框架侧处理时序与变更前一致（无拦截、无改写），仅提示词内容变化

### Requirement: 取证深度上限与输出裁剪

实现者与评审车道的 prompt SHALL 注入「取证深度上限」与「输出裁剪」约束：

- **取证深度上限**：取证 MUST 以**足以判定结论的最小可判反证**为限。评审车道判定 `blocking`（前提被证伪）vs `repairable`（文档内可修）所必需的最小证据之外，MUST NOT 穷尽复现 SPEC 声明的全部断言；实现车道不得为「完整复现」而重复重跑全量套件。
- **输出裁剪**：可能产生大块输出的命令（探针/日志/构建）MUST 裁剪输出——用 `head -c` / 只取关键行 / 落临时文件后只回读关键片段——MUST NOT 将数十 KB 原始输出整块投入对话上下文。

该段为提示词约束，MUST NOT 引入框架侧命令改写。

#### Scenario: 评审车道含取证深度上限
- **WHEN** 构建 `spec-review` 车道 prompt
- **THEN** 含「以最小可判反证为限、MUST NOT 为完整复现穷尽探测」的约束文本

#### Scenario: 探针输出裁剪要求在场
- **WHEN** 构建任一长车道 prompt
- **THEN** 含「探针/大块输出 MUST 裁剪后入对话」的约束文本

#### Scenario: 不引入框架侧命令改写
- **WHEN** agent 发起 Bash 调用
- **THEN** 框架不拦截、不改写其命令（约束仅在提示词层）
