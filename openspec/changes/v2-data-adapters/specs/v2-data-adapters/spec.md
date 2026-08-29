## ADDED Requirements

### Requirement: SPEC 列表适配(排序与 fix 树)

adaptSpecs(rawList) 输出行数组:按 SPEC_LIFECYCLE 生命周期序排序;fix-<父名> 前缀的行归入对应父行的 children(树行),子行含 isFixChild:true,父行聚合子任务进度;字段映射与 behavior.md §1/§2 逐字一致。

#### Scenario: 生命周期排序
- **WHEN** 输入乱序 specs 列表
- **THEN** 输出行的状态索引按 SPEC_LIFECYCLE 严格升序

#### Scenario: fix 树分组
- **WHEN** 列表含 fix-<父名> 子任务
- **THEN** 父行 children 含该子任务且 isFixChild 为 true,父行任务进度已聚合

### Requirement: 计数字段数字化

adaptOverview/adaptSpecDetail 对所有计数字段 Number() 归一(NaN→0),兼容服务端输出字符串 "0" 的历史坑(behavior.md §1)。

#### Scenario: 字符串计数归一
- **WHEN** overview 计数字段为字符串 "0"
- **THEN** 输出为数字 0

### Requirement: 配置适配与三级回退

adaptConfig 对缺失 llm 键兜底 `{providers: []}`;buildConfigPayload(form, snapshot, defaults) 按「表单空/NaN → snapshot → defaults」三级回退合并数字字段(behavior.md §6)。

#### Scenario: llm 缺失兜底
- **WHEN** adaptConfig({}) 
- **THEN** 返回对象 llm 键为 {providers: []}

#### Scenario: 三级回退
- **WHEN** 表单 max_parallel 为空串、快照为 3、默认 2
- **THEN** payload.max_parallel === 3

### Requirement: validateChain 链完整性校验

validateChain(chainValue, providers) 返回 true 或错误文案:必填角色齐全、模型名存在于 provider(规则 behavior.md §6)。

#### Scenario: 缺必填角色
- **WHEN** 链缺少 behavior.md §6 要求的必填角色
- **THEN** 返回非 true 的错误文案
