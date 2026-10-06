# stray-remediation Specification

## Purpose

主树复发型散件从「循环提交」转向「当场根治」：同文件第二次被处置起，admin 有义务执行 untrack 类根治或显式挂账跟踪，消除确定性复发的处置敞口；根治路径一键可达且留痕。

## Requirements

### Requirement: untrack 裁决选项

maintree 散件的裁决空间 MUST 提供 untrack 选项（绑定 maintree_stray_wip_stale 信号）：对告警指认的具体文件执行 git rm --cached、追加 .gitignore 条目（已存在则不重复写）并以独立提交落地；执行 MUST 复用既有 staged 子集守卫与回滚骨架，MUST 在结果中记录 untrack 文件清单与提交号。

#### Scenario: 一键根治生成物日志

- **WHEN** maintree_stray_wip_stale 告警命中被 track 的生成物文件且 admin 选择 untrack 选项
- **THEN** 该文件脱离 git 索引、.gitignore 增加对应条目、独立提交生成且结果含文件清单与提交号，此后该文件改动不再产生 maintree 散件告警

#### Scenario: 非 maintree 散件信号拒绝该选项

- **WHEN** 对未绑定 maintree_stray_wip_stale 的信号尝试 untrack 选项
- **THEN** 选项不可用或执行被拒绝，主树 git 状态不被改动

### Requirement: 复发识别与处置强制

散件告警 MUST 检索同文件历史 maintree_stray_wip_stale 告警与处置并携带「已 N 度处置」计数与根治指引；admin 处置契约 MUST 规定：复发型散件（同文件第 2 次处置起）MUST 当场执行根治（untrack 或等效）或在处置记录挂显式跟踪项，MUST NOT 以「仅提交」第三次收尾；首次处置维持既有「提交+建议」路径不强制根治。

#### Scenario: 第二次处置触发根治义务

- **WHEN** 同一文件第 2 次触发 maintree_stray_wip_stale 且 admin 出具处置
- **THEN** 告警 evidence 含「已 2 度处置」计数与根治指引，处置记录含根治动作或显式跟踪项，二者必有其一

#### Scenario: 首次处置维持现状

- **WHEN** 同一文件首次触发告警
- **THEN** 维持既有「提交+建议」处置路径，不强制根治