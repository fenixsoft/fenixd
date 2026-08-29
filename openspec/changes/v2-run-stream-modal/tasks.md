# Tasks: v2-run-stream-modal

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 8」节(run-stream.js 骨架、Dialog 接入 JSON、测试代码)与计划头部「run-stream.js custom 协议」
- 行为唯一权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §3(run 弹窗全协议)、§4(admin 状态机)

## 1. 测试先行

- [x] 1.1 写 tests/v2/run-stream.spec.js(时间轴节点点击 → Dialog 可见且流内容非空;关闭 → DELETE watch 被发出);跑确认 FAIL(当前是占位 tpl)

## 2. 组件实现

- [x] 2.1 实现 run-stream.js:mount(dom, props) 按 mode 分支;run 模式(tail 快照→render→POST watch→SSE 增量/reset→粘性滚动→thinking_tokens 合并→marked 转义);admin 模式状态机(invoke→409 toast→5s 轮询→admin_run_id→切流);dispose(DELETE watch + close ES);window.RunStream.active 挂载
- [x] 2.2 pages/spec-detail.json 时间轴点击 Dialog 替换为 RunStream 接入(计划 Task 8 Step 3 代码逐字)
- [x] 2.3 run-stream.spec.js PASS;粘性滚动行为人工抽查(Playwright 驱动:上翻不跳底、回底恢复)

## 3. 提交

- [x] 3.1 `git add core/dashboard/static/v2/run-stream.js core/dashboard/static/v2/pages/spec-detail.json tests/v2/ && git commit`(信息:`v2-run-stream: 运行记录弹窗 custom(watch+增量+粘性滚动+token 合并)`)

## 验证修复（第 1 轮失败）

- [x] 阅读 `openspec/changes/v2-run-stream-modal/verification-report.md`，定位「真实产品 Bug」并修复
- [x] 修复后重跑验证确认通过
