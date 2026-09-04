## ADDED Requirements

### Requirement: 统计块与项目卡片渲染

概览页渲染 5 个统计块(字段按 behavior.md §1,经 adaptOverview 数字化)与项目卡片网格(名称、状态、SPEC 计数等,经 adaptProjects)。

#### Scenario: 真实数据渲染
- **WHEN** 访问 /v2/index.html#/overview
- **THEN** 统计数值可见,环境真实项目名出现在卡片中

### Requirement: 项目生命周期控制

每张项目卡提供启动/停止/删除按钮:confirm 确认后调老版同款端点,成功后 toast 并重拉 ov-projects(计划 Task 5 Step 4 动作模式)。

#### Scenario: 启动按钮
- **WHEN** 点击某项目卡「启动」并确认
- **THEN** POST /api/projects/<name>/start 发出,toast 提示,ov-projects 重拉

### Requirement: SSE 触发重拉

ov-stats 监听 sse:state 与 sse:reload…(sse:state + sse:refresh),ov-projects 监听 sse:state,收到后按 componentId reload(节流由桥负责)。

#### Scenario: 数据变化自动反映
- **WHEN** watcher 检测到项目 .fenix 数据变化(如 touch 文件)产生 state 帧
- **THEN** 8s 内 ov-stats/ov-projects 发生重拉(BridgeTest.reloadCount ≥ 2)
