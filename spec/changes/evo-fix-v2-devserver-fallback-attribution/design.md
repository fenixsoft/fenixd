# 设计（fix-v2-devserver-fallback-attribution）

## 现状与根因

- 判据链：core/v2_dev_server.py:464-486 _dev_server_worktree_root 要求 static-root token 含 /worktrees/；回退形态（static_root=…/.fenix/core/dashboard/static，:140-157 推导）必返 None→skip 分支 :533-549 每轮 WARNING 后 continue。
- 无记账：cleanup_orphans（:571-590）每次全量重算，全文件无 pid 记账；告警透传无去重（core/logger.py:223-226）；节拍=启动清扫（fenixd.py:697）+600s 周期（fenixd.py:976-980）。
- 扫描面：全局 pgrep -f（:384-397/:526）不分项目，双 daemon 主机同 pid 双份日志刷屏（本窗口 potplayer 101 条+fenixd 106 条）。
- 豁免逻辑已有：_worktree_has_live_referencing_process（:489-510）可保护 argv 含 /worktrees/ 路径的在服 run——回退形态缺的只是可归因标记。
- 泄漏盲区：_v2_servers 纯内存态（core/agent_runner/v2_server.py:37-48）；ppid 自灭只覆盖 daemon 死亡（dev-server.mjs:146-158）；serving registry 只登记被测实例（pm_engine/verification/serving.py:583）。
- 实况：被警告 pid 30/30 正常回收（存活 4.2h/3.8h/24min），非孤儿；回退形态对非框架目标项目是常态（potplayer-base 30/30 回退）。

## 方案决策

1. **归因恢复双管**：①主改 start() 回退分支（:140-157）给 dev-server argv 附加 worktree 路径标记——不依赖项目布局、改动面最小，且让既有豁免逻辑自然生效、skip 分支消失；②辅改 worktree 侧 core/dashboard/static 软链（core/worktree_manager/lifecycle.py:316 _provision_worktree_deps，create 两出口 :187/:298 共用），消除回退形态本身，软链失败不阻塞 create。同时修正 :142「该形态罕见」的错误注释。
2. **记账而非超期杀**：skip 分支按 pid 记账（首见告警一次、后续静默计数）；升级/处置必须以「无引用进程」判定为前提——**明确不做按裸存活时长的自动 kill**（在服 run 可合法持有 4.2h）。pgrep 按项目收窄，双 daemon 不互刷。
3. **文案联动**：skip 告警文案改条件形态（说明判定局限+误杀风险），移除无条件「可手动 kill」。
4. **重启收口复用成熟形态**：_v2_servers 登记持久化（或 daemon 启动按端口段 19000-19019+argv 对账），只收割无主进程；实现参照 core/serving_registry.py:351-394 的「按 pid 记账+身份核对+收割」形态。

## 风险

- argv 附加改变进程 cmdline：确认不影响既有 pgrep 匹配模式与调试习惯（匹配键仍含 dev-server.mjs 路径）。
- 软链对每个 worktree 增加 provisioning 开销：失败静默降级回退形态（此时由记账+豁免兜底）。
- 重启对账误杀有主进程：以 argv 标记+引用判定双条件收口，测试覆盖「run 在飞时重启 daemon」场景。