# administrator-agent Spec（delta：执行模型改为后台 worker 池并行）

## MODIFIED Requirements

### Requirement: Administrator Agent 按需唤起

Administrator 的唤起与处置执行 SHALL 与 daemon 主循环解耦：主循环只负责拾取手动唤起请求与自动巡检信号并投递，处置在后台 worker 池中执行，主循环调度（SPEC 派发、巡检、请求拾取）不因处置运行而阻塞。 SHALL 支持并行多实例：多个 Administrator run 可同时执行（仍在主树操作，不建 worktree），每个实例的处置状态文件相互独立。

#### Scenario: 手动唤起请求被及时投递

- **WHEN** Dashboard 写入 `.fenix/admin_invoke_request.json` 且 daemon 主循环下一轮扫描拾取
- **THEN** 主循环将该请求投递到 worker 池并在本扫描周期内继续后续工作（总耗时不超过一个扫描周期）
- **THEN** 处置在 worker 线程启动，pending disposition 在 worker 内于执行前落盘（按 run 关联）

#### Scenario: 处置运行期间主循环不停摆

- **WHEN** 一个或多个 Administrator 处置正在后台执行（单次实测可达数分钟）
- **THEN** 主循环仍以 1s 粒度继续 SPEC 派发、admin_monitor 巡检与后续请求拾取
- **THEN** 处置期间到达的新 invoke 请求被拾取并投递，不丢失、不覆盖

#### Scenario: 并行实例处置状态隔离

- **WHEN** 多个 Administrator run 并行执行
- **THEN** 每个 run 使用独立的处置状态文件（`.fenix/admin_disposition-<run_id>.json`），clear/write/read 仅作用于自身实例文件
- **THEN** 提示词中指示 Administrator 写入的路径为该 run 自己的实例文件路径
- **THEN** 单个 run 结束后（读取自身 disposition 落 final 记录）清理自己的实例文件，其它实例不受影响

#### Scenario: 并发数受配置约束

- **WHEN** 待处理请求数超过 worker 数量
- **THEN** 超出部分在队列中等待，worker 空闲后按到达顺序领取执行
- **THEN** worker 数量可配置（默认 2），不无界扩张

#### Scenario: 后台处置失败不丢痕

- **WHEN** 任一 worker 中的处置抛出异常（agent_runner 异常、写入失败等）
- **THEN** 按 `invoke_manual` 既有语义落 failed disposition 与升级告警（记录不因移入后台而丢失）
- **THEN** 该 worker 线程本身不因单次处置异常退出，继续领取队列中的后续请求
