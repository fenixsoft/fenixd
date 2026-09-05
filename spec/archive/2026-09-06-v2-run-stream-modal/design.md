## Context

behavior.md §3(运行弹窗:tail=300 服务端 clamp 2000;事件形态 assistant/user/tool_use/tool_result/error/result/system;watch 订阅协议;reset 语义;粘性滚动阈值;thinking_tokens 合并;marked 渲染转义)与 §4(admin 状态机:POST /api/spec-admin-invoke → 409 toast;等待态 5s 轮询 GET /api/specs/<spec> 解析 admin_run_id;切实时流;关闭 DELETE watch)是行为唯一权威。

## Goals / Non-Goals

- Goals: run 模式全行为;admin 模式状态机实现(接线在 Task 9);dispose 清理(DELETE watch + close ES)
- Non-Goals: 呼叫 Admin 按钮接线(Task 9);toast 时序改动(全局约束 5s/6s)

## Decisions

- **不注册新渲染器**:Dialog body 用原生 type custom + 字符串 onMount 调 window.RunStream.mount;关闭清理挂 Dialog onEvent.close → script 调 dispose(mount 时写 window.RunStream.active;计划 Task 8 Step 3 代码逐字)
- **自管 EventSource**:不走 broadcast——run_events 需携带事件数据增量追加,不适合「广播→重新拉 API」模式(fork 查证结论)
- **粘性滚动**:阈值 40px,接近底部吸底,上翻释放(behavior.md §3)
- **tail 快照先行**:先 GET ?tail=300 渲染,再 POST watch + SSE 增量;reset 帧整段替换

## Risks / Trade-offs

- watch 需要真实 run 数据;测试用环境实况已知 run,无数据时对应断言 fixme 并注释
- 双 EventSource(桥 + run 流)并存:桥已常驻,run 流 ES 仅弹窗存活期存在,关闭即清理
