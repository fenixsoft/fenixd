# daemon-singleton Spec

## ADDED Requirements

### Requirement: 单实例排他锁
Fenixd SHALL 在启动时对专用锁文件获取 flock 排他锁。若锁已被其他实例持有，新启动的实例 MUST 打印「已在运行」提示并立即退出，不得与既有实例并发运行、双派发 agent。

#### Scenario: 第二个 daemon 启动即退出
- **WHEN** 已有一个 fenixd daemon 持有锁，再次启动第二个 daemon
- **THEN** 第二个实例打印提示并以非零退出码退出，不进入主循环

#### Scenario: 正常启动获取锁
- **WHEN** 无其他实例持有锁，daemon 启动
- **THEN** daemon 获取锁并正常进入主循环

#### Scenario: 异常退出后锁自动释放
- **WHEN** daemon 因崩溃/kill 退出
- **THEN** 锁由操作系统自动释放，下次启动可正常获取
