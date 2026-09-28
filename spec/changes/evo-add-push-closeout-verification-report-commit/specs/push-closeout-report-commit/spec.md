# push-closeout-report-commit 能力规格（delta）

## ADDED Requirements

### Requirement: push 收口报告入库

done→pushed 收口时，框架 SHALL 对本 spec 的 spec/changes/<spec>/verification-report.md 执行 pathspec 精确入库（单文件 add+commit，幂等），使「报告落盘晚于实现 merge」的窗口在 pushed 落定前闭合。

#### Scenario: 滞留报告随收口入库

- **WHEN** approve_push 时报告在盘且未入库或有未提交修改
- **THEN** 产生仅含该单文件的提交，其他 spec 的在途草案与 staged 内容不受牵连
- **AND** transition(pushed) 正常落定

#### Scenario: 报告已入库则幂等跳过

- **WHEN** 报告已入库且工作区无该文件差异
- **THEN** 不产生新提交、不产生 WARNING，pushed 照常落定

### Requirement: 失败降级不阻断

报告缺失、项目非 git 仓库或 git 操作失败时，框架 SHALL 仅记录 WARNING 并照常落定 pushed；push 幂等重入 SHALL NOT 产生重复提交。

#### Scenario: git 失败不阻塞收口

- **WHEN** 报告入库因任何 git 错误失败
- **THEN** 记录含 push-closeout 前缀的 WARNING
- **AND** pushed 照常落定，push 主链无感知