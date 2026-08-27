# spec-fix-family-convergence-governor

## ADDED Requirements

### Requirement: 族谱深度与宽度上限
`_on_spec_bug_found` 自动创建 fix 子 SPEC 前 SHALL 计算候选子代的族谱度量：深度 = 规范名中连续 `fix-` 前缀层数；宽度 = 同父（去除一层 fix- 前缀后同根）且状态非 done/pushed 的兄弟数量。深度超过 `pm.family.max_depth`（默认 3）或宽度超过 `pm.family.max_width`（默认 2）时 MUST 中止自动创建，父 SPEC 状态保持 bug-found 不变。

#### Scenario: 四层嵌套请求被拦截
- **WHEN** fix-fix-fix-x 验证失败触发新子代创建请求（将成为第四层）
- **THEN** 不创建新 SPEC，无新分支/工作树，日志记录拦截原因

#### Scenario: 宽度第二兄弟被拦截
- **WHEN** 某 bug-found SPEC 已存在 2 个未完成子代，再次触发派生
- **THEN** 自动创建被中止

### Requirement: 越界转人工处置
被拦截的派生请求 SHALL 转为 `family_explosion` 困境信号（severity=major）写入 admin_alerts 并唤起 Administrator 处置；处置动作「放行一次」为该父 SPEC 设置豁免位 `_family_waiver=true`，使下一轮 bug_found 处理允许再创建一个子 SPEC 且随即清除豁免位。

#### Scenario: 拦截产生信号
- **WHEN** 深度超限的派生请求发生
- **THEN** admin_alerts 新增 kind=disposition/signal_type=family_explosion 记录且 spec 状态未变

#### Scenario: 人工放行后单次通行
- **WHEN** Administrator 对某父 SPEC 执行放行处置
- **THEN** 该父下一轮允许创建恰好一个子 SPEC，豁免位使用后自动复位为 false

### Requirement: 计数口径与既有数据兼容
度量计算 SHALL 基于 STATE 全量读取，不受 fix-dispatch-orphan 引入的字段保留策略（implementer_run 历史值保留）影响；对历史已存在的四层命名（如 add-dashboard-spec-doc-tabs 系）首次扫描即按现值评估，不追溯惩罚已 done/pushed 的祖先。
