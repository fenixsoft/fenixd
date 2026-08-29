## ADDED Requirements

### Requirement: 深链回归

#/config?tab= 直达指定页签(刷新保持);#/spec/:project/:name 直达详情。

#### Scenario: 深链与刷新保持
- **WHEN** 带深链访问并刷新页面
- **THEN** 目标页签/详情正确渲染,路由不回退

### Requirement: 双版并存对比

并存期对 / (老版)跑只读冒烟:#tl-root 可见、SPEC 列表行数与 /v2/ 对应项目相等;老版零新增 pageerror。

#### Scenario: 老版未受影响
- **WHEN** 访问 / 与 /v2/index.html 各自列表页
- **THEN** 老版正常渲染,两版 SPEC 行数相等,均无 JS 错误

### Requirement: 全程零 JS 错误

验收脚本全程收集 pageerror,结束时断言为空数组。

#### Scenario: 干净运行
- **WHEN** 全量验收执行完成
- **THEN** pageerror 集合为空;`npx playwright test` 全绿

### Requirement: 运行手册

tests/v2/RUNBOOK.md 记录:dashboard 启动命令、playwright 环境安装、fixme 用例清单及前置条件、如何对 / 与 /v2/ 分别执行。

#### Scenario: 手册可复现
- **WHEN** 全新环境按 RUNBOOK 步骤操作
- **THEN** 能复跑全部测试并得到一致结果
