## ADDED Requirements

### Requirement: 详情页渲染

#/spec/:project/:name 渲染验证结论卡(verdict 计数已数字化)、验证进度、任务清单 + 4 页签:时间轴(timeline,source=${timeline})、场景结果(table)、Bug(table)、截图(image 网格,src=/screenshots/...,点击放大)。

#### Scenario: 四页签可见
- **WHEN** 访问真实存在的 #/spec/<project>/<spec> 并依次点击页签
- **THEN** 验证卡可见,4 个页签内容区渲染无 JS 错误

#### Scenario: 截图放大
- **WHEN** 点击失败截图页签中的缩略图
- **THEN** 打开放大预览(AMIS image preview)

### Requirement: SSE detail 定向刷新

spec-detail 监听 sse:detail:仅当帧内 spec 名与当前路由 params[1] 一致才 reload;监听 sse:state 无条件 reload。

#### Scenario: 其他 SPEC 的 detail 帧不触发
- **WHEN** 当前在 spec A 详情页,SSE 推来 spec B 的 detail 帧
- **THEN** 页面不重拉(可通过 BridgeTest/网络计数观测)

### Requirement: 时间轴节点弹窗契约

时间轴节点点击打开 size lg Dialog,body 为 type custom(onMount 调 window.RunStream.mount,mode=run,runId 来自节点数据),Dialog close 事件调 dispose——该契约由 Task 8 SPEC 落地,本 SPEC 保证节点点击动作骨架(占位 Dialog)就绪。

#### Scenario: 节点点击开弹窗
- **WHEN** 点击时间轴任一节点
- **THEN** 弹出「运行记录」Dialog(本 SPEC 为占位内容,无 JS 错误)
