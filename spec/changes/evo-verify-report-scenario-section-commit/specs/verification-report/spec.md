# verification-report 能力增量（delta）

## ADDED Requirements

### Requirement: 场景段写盘即入库

验证裁决采纳流程中向 verification-report.md 追加「本轮场景集变更」小节并写盘成功后，框架 SHALL 立即对该报告文件执行 pathspec 精确入库（单文件 add+commit，幂等），使报告在采纳流程结束时不带未入库差异。

#### Scenario: 场景段随写盘入库

- **WHEN** 场景段渲染原子写回成功
- **THEN** 该报告文件被单独提交入库，HEAD 包含小节且该 pathspec 对 HEAD 干净
- **AND** 其他 spec 的在途草案与 staged 内容不受牵连

#### Scenario: 重复触发幂等

- **WHEN** 小节已在库后再次触发渲染与提交
- **THEN** 不产生新提交、不产生 WARNING

### Requirement: 提交失败降级

场景段入库的 git 操作失败或项目非 git 仓库时，框架 SHALL 仅记录 WARNING：渲染写盘结论与验证裁决主流程不变，非 git 项目静默跳过。

#### Scenario: git 失败不扰主流程

- **WHEN** 场景段提交因 git 错误失败
- **THEN** 记录 WARNING，写盘结果与裁决采纳行为不变