## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_knowledge_distill_resume.py
  kind: new
```

## 1. pending 台账持久化（core/knowledge.py）

- [ ] 1.1 core/knowledge.py：DistillManager 新增台账读写辅助——读 `<proot>/.fenix/knowledge-distill-pending.json`（缺失/损坏按空表 fail-open）、原子回写（tmp+os.replace、读-过滤-写防并发丢条目）。
- [ ] 1.2 core/knowledge.py：dispatch 单点入队时把本批归档名（含 queued_at 时间戳）追加进台账；回填期排队（backfill-queued）与各门控拒绝路径不写台账。
- [ ] 1.3 core/knowledge.py：批次成功收尾（_commit_output 返回非 None，含无变更）与 _give_up 清理确认（_discard_output=True）后移除对应条目；「校验通过但自动提交失败」「执行异常」「回滚未确认」路径保留条目并在既有 todo 台账文案中注明将由重启续跑接管；同项目积压合并为一次 run 的批次按本批 names 并集一次清除全部对应条目（防漏清陈旧条目引发重启后重蒸）。

## 2. 启动恢复与自愈盲区（fenixd.py）

- [ ] 2.1 core/knowledge.py：新增 DistillManager.recover_pending(proot)——读台账、先清空台账、逐条走既有门控链（_gate_distill + _dispatch_via_mgr）重新入队（门控放行条目由 dispatch 写点重新落盘、拒绝条目不复活）、返回恢复数；仅由 daemon 启动路径调用。
- [ ] 2.2 fenixd.py：FenixDaemon.initialize 末尾调用 recover_pending，恢复数 >0 时落日志「knowledge-distill 恢复重派（N 批：…）」；dashboard --serve 路径不接入。
- [ ] 2.3 fenixd.py：_is_idle 新增蒸馏维度——worker 线程存活或进程内队列非空判非空闲；getattr 容错（缺失按空闲、异常按非空闲）；注释写明「单批 ≤ RUN_TIMEOUT_SECONDS×(1+MAX_FIX_ROUNDS)、worker 存活上界 = 积批数×单批上界」的有界性依据与「死台账不判非空闲」口径。

## 3. 测试（tests/test_knowledge_distill_resume.py）

- [ ] 3.1 tests/test_knowledge_distill_resume.py：dispatch 后台账含条目、批次完成后条目消失、_give_up 清理确认后条目消失、提交失败滞留路径条目保留、门控拒绝路径不写台账、同项目连续派发两条被合并为一次 run 时收尾后两条目一并消失。
- [ ] 3.2 tests/test_knowledge_distill_resume.py：台账损坏/非法 JSON 按空表处理且派发不受阻；原子回写在并发入队下不丢条目（多归档批量 + 交错单条）。
- [ ] 3.3 tests/test_knowledge_distill_resume.py：recover_pending 先清空台账后重新入队（成功入队条目重新落盘、门控拒绝条目不复活）、恢复批次经 worker 消费完成入库提交且完成后台账条目消失（注入替身 spawn）、归档目录已缺失时恢复路径按门控拒绝且条目不复活。
- [ ] 3.4 tests/test_knowledge_distill_resume.py：_is_idle 蒸馏维度——worker 在飞/队列非空返回 False、DistillManager 替身缺属性时按空闲不抛异常、异常注入时按非空闲。