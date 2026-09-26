# verification-report：落盘即入库

## ADDED Requirements

### Requirement: 验证报告写盘成功后立即入库
ensure_verification_report 在报告文件写盘成功后（含验证 Agent 已自写报告、闸门以 present 放行的情形——该路径框架不落盘但文件已在盘，同样入库），对 spec/changes/<spec>/verification-report.md 执行 pathspec 精确的 git add 与 commit（add 与 commit 同 pathspec）；提交信息注明所属 spec。

#### Scenario: 报告落盘后工作区不再滞留
- WHEN 验证裁决完成、报告写盘成功
- THEN 该文件已随单文件提交进入版本库，git status 不再显示其为未跟踪

#### Scenario: 两路生成均被覆盖
- WHEN 报告由验证 Agent 写入或由框架合成（synthesize_verification_report）
- THEN 两条路径都经过 ensure_verification_report 汇聚，均触发入库

### Requirement: git 异常不阻塞验证链
提交失败（git 不可用、锁冲突等）只落 WARNING 日志，报告文件保留在磁盘，验证主流程与函数返回值不受影响；报告已入库且内容未再变化时静默跳过提交，不落 WARNING。

#### Scenario: 提交失败降级为告警
- WHEN 入库时 git 命令非零退出
- THEN 落 WARNING 日志，ensure_verification_report 仍按写盘成功返回，验证流程继续

#### Scenario: 重复放行不重复告警
- WHEN 报告已入库且此后内容未再变化，闸门再次放行
- THEN 跳过提交且不落 WARNING，验证流程继续

### Requirement: 内容认可判定不受影响
入库动作不得把 verification-report.md 计入 spec 内容认可（spec_has_content）判定，不得扩大 pathspec 范围到其它文件。

#### Scenario: 提交范围严格单文件
- WHEN 触发报告入库
- THEN git add 与 commit 的 pathspec 仅含本 spec 的 verification-report.md，不卷入其它 spec 的任何在途文件