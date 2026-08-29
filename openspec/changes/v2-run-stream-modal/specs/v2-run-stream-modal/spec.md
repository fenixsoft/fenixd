## ADDED Requirements

### Requirement: run 模式实时流

props mode=run, runId:打开即 GET /api/runs/<runId>?tail=300 渲染尾部,然后 POST /api/runs/<runId>/watch?cid=<Bridge.cid> 订阅;SSE run_events 帧(run_id 匹配)增量追加,reset 帧整段替换;事件按 behavior.md §3 形态渲染(含 thinking_tokens 合并、marked 转义);粘性滚动(40px 阈值,上翻释放、回底恢复)。

#### Scenario: 打开弹窗拉取尾部并实时追加
- **WHEN** 有真实 run 的 SPEC 详情页点击时间轴节点
- **THEN** Dialog 可见且事件流非空;watch 订阅发出;新事件到达时若在底部则自动滚到底

### Requirement: 关闭清理

Dialog close 时 DELETE /api/runs/<runId>/watch?cid= 并 close 本组件的 EventSource。

#### Scenario: 关闭即退订
- **WHEN** 关闭运行记录 Dialog
- **THEN** DELETE watch 请求发出(run-stream.spec 用 page.route 拦截断言),ES 关闭

### Requirement: admin 模式状态机

props mode=admin, project, spec:先 POST /api/spec-admin-invoke——409 时错误 toast 并终止;成功进入等待态,每 5s GET /api/specs/<spec> 解析 admin_run_id;拿到后按 run 模式拉流;关闭时同样清理(behavior.md §4)。

#### Scenario: 等待态与流切换
- **WHEN** admin invoke 成功(等待期)
- **THEN** 显示等待态;admin_run_id 出现后自动切换为实时流渲染

#### Scenario: 409 处置中
- **WHEN** POST /api/spec-admin-invoke 返回 409
- **THEN** 错误 toast(6s 窗口内可见)且不发 watch
