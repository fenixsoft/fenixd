<!-- knowledge: capability=done-push-dedup rev=1 sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races -->

# done→pushed 自动审批单飞

自动推送链路的并发去重：同一 SPEC 的 done→pushed 迁移与 git push 全程只执行一次。

## 现行规则

- `approve_push` 在实例级互斥锁内执行完整 check-then-act：acquire → 重读 spec status → 非 done 幂等跳过（返回 True）→ git push → transition(pushed) → release。
- 并发的第二个执行流在锁上排队，进入后见 pushed 即幂等跳过：不重复执行 git push、不产生重复 project log、不触发 pushed→pushed 非法迁移 ERROR。
- 不同 SPEC 的 approve_push 经全局锁串行执行，git push main 无并发竞态。

## 溯源

- 2026-09-12 fix-daemon-lifecycle-races（spec/archive/2026-09-12-fix-daemon-lifecycle-races） — 将 verify 成功同步直调与 event_bus spec_done 事件的双路径并发收编为锁内 check-then-act 单飞，消除重复 push 与假 ERROR 告警
