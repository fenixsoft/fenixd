# fix-v2-devserver-fallback-attribution

## 背景

2026-10-02/03 窗口，potplayer-base 日志产生 101 条「orphan sweep skipped … argv carries no worktree path」WARNING，fenixd 自身日志另有 106 条同 pid 警告。核查证实：被警告进程全部是在服 run 的正常 dev-server 且 30/30 被正常回收——不是孤儿堆积，而是主树静态根回退形态（非框架目标项目 git 无 core/dashboard，30/30 回退）进程 argv 无 /worktrees/ 路径，被清扫判据（core/v2_dev_server.py:464-486）永久判为不可归因，每 600 秒误报一次；清扫用全局 pgrep 不分项目（:384-397/:526），双 daemon 主机下同 pid 在两份日志各刷一条。告警文案建议「可手动 kill」，run 期照做会打断验证（V2_BASE_URL 悬挂）。另有零实发的真实泄漏盲区：_v2_servers 纯内存态（core/agent_runner/v2_server.py:37-48），daemon 重启后无主回退形态进程永久无人收割。

## 目标

1. 回退形态可归因：start() 回退分支给 dev-server argv 附加 worktree 路径标记，并给 worktree 补 core/dashboard/static 软链，使既有豁免逻辑（_worktree_has_live_referencing_process :489-510）能保护在服 run，skip 误报自然消失。
2. 残余不可归因进程按 pid 记账：首见告警一次、后续静默计数；升级/处置以「无引用进程」为前提，禁止按裸存活时长自动 kill。
3. 告警文案纠偏：移除无条件「可手动 kill」建议，改为与归因/引用判定联动的条件文案。
4. 重启泄漏盲区收口：daemon 重启后能识别并收割无主 dev-server，不误杀有主进程。

## 非目标

- 不改端口段分配与确定性跳过逻辑（core/v2_dev_server.py:26-27）。
- 不改 serving registry（core/serving_registry.py）对被测实例的既有语义（其「按 pid 记账+身份核对+收割」形态仅作实现参照）。

## 验收

- 非框架目标项目（回退形态常态）下：在服 run 的 dev-server 不再产生周期性 skip 告警，run 结束后被正常收割。
- 同一 pid 的 skip 告警首见一次、后续静默计数；双 daemon 下不互刷（扫描面按项目收窄）。
- daemon 重启后启动对账只收割无主进程，有主进程保留。
- 既有 dev-server/worktree 生命周期测试不回退（tests/test_v2_dev_server*.py 等）。