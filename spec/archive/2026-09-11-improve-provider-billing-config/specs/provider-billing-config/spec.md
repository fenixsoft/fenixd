# provider-billing-config

计费配置收敛到 Provider 卡片：卡片级启用开关、价格行交互、存储结构内嵌、按卡片开关与模型匹配的计价闸门。

## ADDED Requirements

### Requirement: Provider 卡片级计费开关
每个 Provider 卡片内部 SHALL 拥有独立的「启用计费」开关（Switch）；模型页签 MUST NOT 再渲染面板级全局「启用计费信息」开关。价格编辑区 MUST 仅在该卡片开关开启时出现；开关关闭的卡片 MUST NOT 参与任何成本计算。

#### Scenario: 开启卡片开关显示价格编辑区
- **WHEN** 用户在 Provider X 卡片内打开「启用计费」开关
- **THEN** 该卡片内出现计费价格编辑区（价格行列表 + 新增按钮），其他未开启的卡片不出现

#### Scenario: 面板无全局计费开关
- **WHEN** 用户进入设置页模型页签
- **THEN** 页面中不存在面板级「启用计费信息」全局开关，仅各 Provider 卡片内各有独立开关

#### Scenario: 关闭卡片开关隐藏价格编辑区
- **WHEN** 用户关闭某 Provider 卡片的「启用计费」开关
- **THEN** 该卡片的价格编辑区隐藏，已填价格在重新开启后保留（本次会话内）

### Requirement: 价格行归属卡片并自动预填模型名
价格行 MUST 归属其所在 Provider 卡片（MUST NOT 提供 Provider 选择框）。新增价格行时，模型名输入框 MUST 自动预填该卡片「默认模型名」字段当前的值，用户可修改（支持同 Provider 多模型价格）。同一卡片内价格行的模型名 MUST 唯一，重复时保存被拦截并提示。

#### Scenario: 新增价格行自动预填默认模型名
- **WHEN** 卡片「默认模型名」为 deepseek-v4-flash，用户点击「添加模型价格」
- **THEN** 新价格行的模型名输入框预填 deepseek-v4-flash，且可编辑为其他模型名

#### Scenario: 同卡片模型名重复被拦截
- **WHEN** 同一卡片内两行价格的模型名相同（如均为 deepseek-v4-flash）且用户点击保存
- **THEN** 保存被阻止，提示存在重复模型名的价格行

#### Scenario: 价格行无 Provider 选择框
- **WHEN** 用户查看或编辑任一价格行
- **THEN** 行内仅有模型名与 4 项单价输入，不存在 Provider 下拉选择框

### Requirement: 单价输入布局与金额约束
4 项单价（输入 / 输出 / 缓存读 / 缓存写）SHALL 以每行两项、带标题栏的布局呈现（Form.Item label 展示字段名，标注单位 $/1M tokens），与「名称 / Base URL」行的布局范式一致。4 项单价输入框 MUST 仅接受正数金额（数字与小数点），其他字符输入 MUST NOT 产生非法值；模型名为必填，4 项单价为必填。

#### Scenario: 单价两列布局带标题
- **WHEN** 用户查看开启计费的卡片价格行
- **THEN** 4 项单价以每行两项、上方带标题栏（输入 / 输出 / 缓存读 / 缓存写，含 $/1M tokens 单位说明）的网格布局渲染

#### Scenario: 非法字符无法输入为值
- **WHEN** 用户在单价输入框尝试输入字母、负号等非金额字符
- **THEN** 输入框不接受这些字符（值保持合法金额形态），不再出现任意字符可输入的情况

### Requirement: 计费配置内嵌 Provider 存储
计费配置 MUST 内嵌于每个 Provider 对象：`llm.providers[i].billing = {enabled: bool, prices: [{model, input_per_million, output_per_million, cache_read_per_million, cache_creation_per_million}]}`；顶层 `llm.billing` 段 MUST 移除。保存设置后 config.yaml 的 `llm.providers` MUST 符合该结构；因存量配置无价格数据（billing 为空），MUST NOT 实现旧结构迁移或双读兼容。

#### Scenario: 保存后落盘新结构
- **WHEN** 用户在 Provider X 卡片开启计费、填写一行价格并保存
- **THEN** config.yaml 中该 provider 对象包含 `billing: {enabled: true, prices: [{model: ..., 4项单价}]}`，文件中不存在顶层 `llm.billing`

#### Scenario: 未开启计费的卡片不写入价格
- **WHEN** 用户保存设置且某卡片「启用计费」为关闭
- **THEN** 该 provider 对象不包含 billing 价格数据（billing 缺省或 enabled: false 且无生效价格行）

### Requirement: 计费配置保存校验
保存配置时后端 MUST 按 Provider 校验 billing 子对象：enabled 为布尔；prices 为列表且每行 model 为非空字符串、4 项单价为非负数值（bool 除外）、行 model 在同一卡片内不重复；任一非法 MUST 拒绝写入并在错误信息中列出违规项（不静默忽略）。

#### Scenario: 非法价格被拒绝写入
- **WHEN** 保存请求中某 provider 的 billing.prices 行单价为负数或 model 为空
- **THEN** 保存失败，返回错误并列出违规行（如 `providers[0].billing.prices[0]` 相关描述），config.yaml 不被修改

#### Scenario: 合法配置保存成功
- **WHEN** 保存请求中各卡片 billing 结构合法（开关布尔、模型名非空、单价非负数值、卡片内不重复）
- **THEN** 保存成功，配置落盘

### Requirement: 计价闸门与匹配语义
单 run 成本 SHALL 仅当 run 实际驱动网关（provider_marker 的 provider）对应 Provider 卡片的 billing.enabled 为真时计算；匹配规则为该卡片价格行的 model 等于 run 实际模型（provider_marker 的 model）。未开启计费的 provider、无匹配价格行、usage 缺失或价格字段残缺的 run MUST 不下发成本字段（成本不可用，MUST NOT 回退网关回传金额）。SPEC 级成本合计 SHALL 仅累计已计价 run。failover 切换后成本 SHALL 按实际完成 run 的网关归属。

#### Scenario: 未开启计费的 provider 不计价
- **WHEN** run 的实际网关 provider 卡片「启用计费」为关闭
- **THEN** 该 run 在 timeline 中不下发 cost 字段（前端不渲染成本），SPEC 级合计不计入该 run

#### Scenario: 开启且模型匹配时现算成本
- **WHEN** run 的实际网关 provider 卡片计费开启，且其价格行 model 等于 run 实际模型，usage 四分项齐全
- **THEN** cost_usd = Σ(token/1M × 对应单价) 现算并随 timeline 下发，SPEC 级合计计入该 run

#### Scenario: 模型不匹配时成本不可用
- **WHEN** run 实际模型 ≠ 该卡片任一价格行的 model（即使计费开启）
- **THEN** 该 run 不下发 cost 字段，SPEC 级合计按不可计价 run 统计（unpriced_runs 计数）

#### Scenario: failover 切换后按实际网关归属
- **WHEN** 某 run 经 failover 由 provider A 切换到 provider B 完成（B 卡片计费开启）
- **THEN** 成本按 provider B 的卡片价格与 usage 计算，与 provider A 的配置无关
