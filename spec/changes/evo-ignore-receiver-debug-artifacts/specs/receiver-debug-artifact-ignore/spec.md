## ADDED Requirements

### Requirement: 调试产物目录 ignore 豁免
.gitignore SHALL 包含 .debug/ 目录条目（含中文注释说明为 receiver 真机调试帧存/日志落点）；该目录 MUST 被 git check-ignore 命中，且 git status --porcelain -uall 对其零输出。

#### Scenario: check-ignore 命中
- **WHEN** 执行 git check-ignore -v .debug/
- **THEN** 命中新追加的 .gitignore 条目并输出规则行号

#### Scenario: porcelain 零输出
- **WHEN** 执行 git status --porcelain -uall
- **THEN** 输出中不含任何 .debug/ 路径条目

### Requirement: 散件巡检面整体免疫
.gitignore 追加后，散件巡检（maintree-stray-wip-sweep）MUST 不再把 .debug/ 下路径计为散件，info 告警与第二档升级（maintree_untracked_stray_escalated）均不可达。现状（2026-10-12 评审实测）：.debug/ 目录已消失，stray_untracked_registry.json 已为空 {}——原指纹 ff7ba4707455188d 条目已按「指纹消失自动复位」清除，升级前提已解除；本免疫面向该目录随下次 receiver 真机调试复发后的会话。

#### Scenario: 复发后不入注册表
- **WHEN** 目录复发后经一轮散件盘点（daemon 300 秒周期）
- **THEN** .debug/ 下路径因 ignore 命中走既有豁免（无规则命中才计散件），注册表不产生新条目，maintree_untracked_stray_stale 告警不产生

#### Scenario: 升级已先触发的收口
- **WHEN** major 升级告警在 ignore 落地前已触发（当前实测未触发：注册表已空、倒计时前提已消失，本场景预期不执行）
- **THEN** 以既有 admin 裁决 ignore_untracked_stray 收口并在处置记录注明，不重复建设

### Requirement: 现场零扰动
本变更 MUST NOT 移动、重命名或删除 .debug/ 下任何现有文件，MUST NOT 影响接收器后续调试会话继续写入该目录。现状（2026-10-12 评审实测）：.debug/ 目录已不存在，本约束适用于落地时目录已复发的情形，且 MUST NOT 为验证而重建该目录。

#### Scenario: 文件原地保留
- **WHEN** ignore 落地前后对比 .debug/ 目录内容（目录存在时）
- **THEN** 既有文件原路径原样存在；目录不存在时（当前实测状态）确认零创建、零重建即可