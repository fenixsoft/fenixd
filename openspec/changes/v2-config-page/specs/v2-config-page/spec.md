## ADDED Requirements

### Requirement: 配置加载回显与保存

页面加载后 5 页签回显当前配置(llm 缺失兜底);修改任意字段保存后 POST /api/config(buildConfigPayload 合并),成功 toast「保存成功」(5s 窗口);重载后新值回显。

#### Scenario: 保存回显闭环
- **WHEN** 修改并行度数字并保存、重新加载页面
- **THEN** 保存期间 toast 出现,重载后显示新值

### Requirement: Agent 链编辑与校验

Agent 模型页签为可排序多行编辑器(input-array sortable:角色 select + 模型名,角色枚举 behavior.md §6);链不满足完整性(必填角色缺失/模型名不存在)时保存被 validateChain 拦截并显示错误文案。

#### Scenario: 不完整链被拦截
- **WHEN** 链缺少必填角色并提交
- **THEN** 表单校验失败,错误文案可见,不发 POST

### Requirement: 编辑豁免 SSE

config 页不监听任何 sse:* 广播(编辑中任何 SSE 帧不得触发本页 reload)。

#### Scenario: 编辑期间不被打断
- **WHEN** 在输入框聚焦输入过程中后端产生 state/refresh 帧
- **THEN** 表单值与焦点不被清空(无 reload 发生)
