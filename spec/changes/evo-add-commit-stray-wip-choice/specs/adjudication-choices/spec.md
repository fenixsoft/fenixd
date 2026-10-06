# adjudication-choices Specification

## Purpose

为 maintree_stray_wip_stale 信号注册标准处置选项 commit_stray_wip，把四次一遇的同型自由裁决收敛为一次登记的标准动作；信号发射时直接带出选项，Dashboard 与处置会话可一键执行并留痕提交 hash。

## Requirements

### Requirement: 注册 commit_stray_wip 选项

裁决选项注册表 MUST 为 maintree_stray_wip_stale 提供 commit_stray_wip 选项：全局信号作用域（spec_scoped=False）、语义为核对归属后直接提交信号清单内散件改动、与 stash 类动作互斥。

#### Scenario: 信号可裁决

- **WHEN** maintree_stray_wip_stale 信号产生
- **THEN** choices_for 返回含 commit_stray_wip，is_adjudicable 为真，Dashboard 告警卡出现该选项

### Requirement: 执行器受清单约束

commit_stray_wip 执行 MUST 只提交信号清单内（或当刻 git status 中匹配信号描述）的文件，拒绝任意路径；执行结果 MUST 在处置记录附提交 hash。执行 MUST 仅接受 signal_type=maintree_stray_wip_stale（其余信号类型——含未注册信号——一律拒绝，不经非作用域全表反查通道触达本动作）。

#### Scenario: 清单外文件拒绝

- **WHEN** 执行请求携带信号清单之外的路径
- **THEN** 执行被拒绝并返回原因，不做任何 git 写

#### Scenario: 正常执行留痕

- **WHEN** 对清单内散件改动执行该选项
- **THEN** 产生一个提交且处置记录含提交 hash

#### Scenario: 跨信号触达拒绝

- **WHEN** 以 maintree_stray_wip_stale 之外的 signal_type（含未注册信号）请求执行 commit_stray_wip
- **THEN** 执行被拒绝且不产生任何 git 写

### Requirement: 发射点带出选项

信号发射记录 MUST 附 choices 快照，recommended_action 文案 MUST 带出 commit_stray_wip；注册表与 SIGNAL_RECOMMENDATION 双处文案保持同步。

#### Scenario: 记录自带选项

- **WHEN** 新的 maintree_stray_wip_stale 信号落库
- **THEN** 记录含 choices 快照且 recommended_action 提及该选项 id