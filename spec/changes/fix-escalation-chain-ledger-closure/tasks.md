## Deliverables

```yaml
- path: core/admin_store.py
  kind: modify
- path: core/admin_choice_exec.py
  kind: new
- path: core/admin_monitor.py
  kind: modify
- path: core/pm_engine/escalation_chain.py
  kind: modify
- path: tests/test_escalation_chain.py
  kind: modify
- path: tests/test_admin_disposition_reschedule.py
  kind: modify
```

## 1. 链侧终态落账单点

- [ ] 1.1 AdminStore 新增 final 落账助手（duck-typed 读 disp，字段形状单源对齐 _worker
      final append 全字段：signal_type/spec/severity/description/action_taken/result/
      recommended_action/summary/admin_run_id/escalate/error/failure_evidence/choice_id/
      suggested_choice/choice_payload；append 异常 try/except 返回 False + WARN 留痕含
      run_id；不 import agent_runner）
- [ ] 1.2 admin_monitor._worker 的 final append 改调助手，行为回归零变化（直接路径
      既有用例全绿为锚）
- [ ] 1.3 escalation_chain._run_admin_phase 在 run_administrator 返回后、分支判定前
      调用助手落账（closed/handoff/exhausted 三出口一次覆盖；落账先于链 closed 事件的
      时序不变式）
- [ ] 1.4 落账不变式守卫测试：复刻首例事件 …6474 时间轴（链派发→成功/转单/耗尽三形态）
      断言 admin_alerts 中存在带该 run_id 的非 pending 处置记录；契约测试比对直接路径
      与链路径产出记录字段形状一致

## 2. 链成功路径 choice 执行

- [ ] 2.1 抽离 _apply_choice_execution 与 _persist_choice_step_records 执行核心为新模块 core/admin_choice_exec.py 模块级函数；AdminMonitor 同名方法委托之（直接路径行为回归零变化，既有用例全绿为锚；dashboard data 层 lazy import 形态保持）
- [ ] 2.2 链 closed 出口接执行：越界白名单复核保持先行 → execute_choice_for_disposition
      → persist_choice_step_records → 成功才 _close_chain_success；执行失败/跳过
      fail-closed（不写 chain-closed、计一次失败、error 注入链事件留痕）
- [ ] 2.3 链侧 choice 用例：payload 型 choice 链上生效（执行器被调 + 逐动作记录落账 +
      闭环事件后置）/ 执行失败不伪造闭环 / 白名单外 choice 保持转单不执行

## 3. 归因子型与看护兜底

- [ ] 3.1 _orphan_run_attribution 读 result 子型：success →「处置结论成功但 final 处置
      记录缺失（落账缺口或收尾中断）——先核对处置台账与链事件再定处置」；非 success
      保持既有文案（回归锚）
- [ ] 3.2 链事件写侧：admin 相事件（chain-closed/chain-handoff）run_id 字段落实际
      admin run id；arbiter 相事件语义不变
- [ ] 3.3 链单例新增 chain_events_for_run(run_id) 只读聚合查询口；孤儿看护 pending
      分支升级前联查——命中 chain-closed/chain-handoff 补终结记录（result=resolved +
      admin_run_id 落该 run id（by_run 归并闭合前提）+ 对账注记）不升级人工；
      查询异常按零命中放行（fail-open）
- [ ] 3.4 看护侧用例：success 归因新文案且不含「非成功结论」/ 非 success 文案不变回归锚 /
      chain-closed 在场不升级只终结 / chain-handoff 同款 / 台账缺失 fail-open 照常升级

## 4. 收尾

- [ ] 4.1 全量回归通过 + compileall 自证
- [ ] 4.2 落位 restart_request 信号文件（根路径，JSON：reason/origin/date）并冒烟预演
      （全新进程 + 消费方 import + 链/看护核心 API）；实际重启由 supervisor 消费该信号完成
