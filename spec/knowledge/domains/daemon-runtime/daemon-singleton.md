<!-- knowledge: capability=daemon-singleton rev=1 sources=spec/archive/2026-09-02-fix-fenix-token-waste -->

# daemon 单例保证

同一项目同时只允许一个 fenixd daemon 实例运行，杜绝双 daemon 并发读 `STATE.md` 造成双派发 agent。

## 现行规则

- daemon 启动时对 `.fenix/daemon.lock` 获取 flock 排他锁（非阻塞）；锁已被其他实例持有时，新实例打印「已在运行」提示并以非零退出码退出，不进入主循环。
- 锁获取先于业务初始化，单例互斥覆盖 supervisor 托管场景——托管拉起与手工启动竞争同一把锁，双实例无从并发。
- daemon 因崩溃或 kill 异常退出时，锁由操作系统自动释放，下次启动可正常获取。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：启动前探测既有实例，双实例被拒；单例互斥覆盖 supervisor 托管场景
- 2026-09-02 fix-fenix-token-waste（spec/archive/2026-09-02-fix-fenix-token-waste） — 固化为 `.fenix/daemon.lock` 上的 flock 排他锁：锁被持有即打印提示并以非零码退出
