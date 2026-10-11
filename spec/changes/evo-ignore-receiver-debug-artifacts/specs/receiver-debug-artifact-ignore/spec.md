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
.gitignore 追加后，散件巡检（maintree-stray-wip-sweep）MUST 不再把 .debug/ 下路径计为散件：stray_untracked_registry.json 中指纹 ff7ba4707455188d 条目随下一轮盘点按「指纹消失自动复位」清除，info 告警与第二档升级（maintree_untracked_stray_escalated）均不可达。

#### Scenario: 指纹复位
- **WHEN** ignore 落地后等待下一轮散件盘点（daemon 300 秒周期）
- **THEN** 注册表中该指纹条目被自动复位清除，不再产生新的 maintree_untracked_stray_stale 告警

#### Scenario: 升级已先触发的收口
- **WHEN** major 升级告警在 ignore 落地前已触发
- **THEN** 以既有 admin 裁决 ignore_untracked_stray 收口并在处置记录注明，不重复建设

### Requirement: 现场零扰动
本变更 MUST NOT 移动、重命名或删除 .debug/ 下任何现有文件，MUST NOT 影响接收器后续调试会话继续写入该目录。

#### Scenario: 文件原地保留
- **WHEN** ignore 落地前后对比 .debug/ 目录内容
- **THEN** 9 个既有文件（3 个会话子目录的帧存与日志）原路径原样存在