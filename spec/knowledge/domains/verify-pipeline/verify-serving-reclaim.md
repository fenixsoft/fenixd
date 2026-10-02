# 验证服务磁盘回收
<!-- knowledge: capability=verify-serving-reclaim rev=1 sources=spec/archive/2026-09-23-fix-verify-serving-disk-reclaim -->

`.fenix/verify-serving/` 下 serving worktree 目录与 `<spec>-boot.log` 的生命周期回收：保留集 fail-safe 判定、启动 reconcile 加周期清扫。

## 现行规则

- 保留集判据（fail-safe，满足任一即保留）：① 归属 spec 存活——目录名按 `{spec}-{10 位 Unix 时间戳}` 约定解析出 spec 名（spec 名自身含短数字后缀时末段 10 位时间戳正确剥离），且该 spec 目录存在于 `spec/changes/` 或 `spec/archive/`（归档等同存活，便于回溯证据）；② 登记在册——目录绝对路径（`Path.resolve()` 后）与 `.fenix/verify-serving/servers.json` 任一条目的 `worktree` 字段全等（`worktree` 为空串的登记项不参与匹配）；③ 活进程占用——进程表存在 argv 或 cwd 指向该目录的存活进程；④ 近期新建宽限——创建/修改时间在 `RECLAIM_GRACE_SECONDS`（600s）之内（防与并发创建竞态）。四条皆不满足的条目回收；无法按命名约定解析归属的条目 fail-safe 保留。
- 清扫执行语义：以 `git worktree remove --force` 回收无主目录，回收后执行 `git worktree prune` 清理 git 侧登记；单条目回收失败记 WARNING 并继续处理其余条目，不中断清扫整体或阻塞 daemon；回收幂等（目录已不存在安全跳过）；不触碰 `servers.json`、`servers.json.lock`、`contract_selfcheck.json` 等顶层状态文件。
- 触发点：daemon 启动时执行一次全量 reconcile（`use_in_flight=False`，前一轮实例视为非在飞）；复用既有 600s 周期孤儿清扫节拍执行周期清扫（`use_in_flight=True`，保留 testing 中 spec 的目录）。启动 reconcile 抛异常记 ERROR 并继续 daemon 启动。
- boot.log 回收：按与目录相同的「无主」判据回收 `<spec>-boot.log`——spec 名由文件名剥离 `-boot.log` 后缀得到（不含时间戳，不复用目录名的解析规则），该 spec 名在 `spec/changes/` 与 `spec/archive/`（按 `*-<spec>` 后缀匹配）均不存在且无在飞 run 时回收；无法解析归属的文件 fail-safe 保留。
- 清扫开关：`verify.serving_reclaim.enabled` 缺省 `true`；为 `false` 时清扫早退（不调 git、不删任何条目）；Dashboard 验证契约页提供该开关且缺省为开，保存路径把该键纳入验证页受管键集合（否则写入被静默丢弃）。
- 可观测性：清扫后记录回收条目数与保留条目数，供 dashboard / 运维追溯。

## 溯源

- 2026-09-23 fix-verify-serving-disk-reclaim（spec/archive/2026-09-23-fix-verify-serving-disk-reclaim） — 新增 serving 目录与 boot.log 的生命周期回收（既有回收入口只在 spec 转 done 且内存缓存在手时触发，daemon 重启或 spec 未经 done 后线索丢失、目录永久残留，实测 19 个 worktree 占 30G）
