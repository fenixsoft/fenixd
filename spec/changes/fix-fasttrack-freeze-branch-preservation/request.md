# 立项请求（用户原话照录，2026-11-09 16:49，消息 m00323）

> 1.接收故障注入代替验收。2.对"fast-track 冻结未保全分支"立项，full，立即执行

- 第 1 项是当时会话里对 single-app-realdevice-retest 任务 5.1 的人工裁决（已在 cloud-phone 侧落地，与本 SPEC 无关）。
- 第 2 项即本 SPEC 的立项指令：针对「fast-track 冻结未保全分支」缺陷，full 模式，立即执行。

## 事故背景（缺陷的实证现场，cloud-phone 2026-11-09）

- spec `single-app-realdevice-retest`：fast-track 实现者诚实申报 `status=partial`（5.1 环境漂移不可满足），同指纹自动重试 3/3 轮耗尽后 `freeze_for_human` 冻结转人工。
- 冻结时 `_frozen_hold: False`、`branch: null`；实现分支 `fenix/single-app-realdevice-retest-<ts>`（13 个提交，验证 5 场景全 pass、verdict=verified）连同 worktree 被清理，**无 pre-rmtree snapshot**——对比同日 m3/p2p/m0 各清理路径均产出了 `fenix: pre-rmtree snapshot <branch>` 快照提交。
- 13 个提交最终仅以悬空对象幸存（冻结后约 3.5 小时经 `git fsck` 抢救，手工建保护分支 + 补记 `_frozen_hold`/branch 锚点后才走通 unfreeze 续做通道）。若 `git gc` 先行，工作全部丢失。
