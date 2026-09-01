# administrator-agent Spec（delta：执行模型改为后台串行队列）

## MODIFIED Requirements

### Requirement: Administrator Agent 按需唤起

Administrator 的唤起与处置执行 SHALL 与 daemon 主循环解耦：主循环只负责拾取手动唤起请求与自动巡检信号并投递，处置本身在后台工作线程中执行，主循环调度（SPEC 派发、巡检、请求拾取）不因处置运行而阻塞。

#### Scenario: 手动唤起请求被及时投递

- **WHEN** Dashboard 写入 `.fenix/admin_invoke_request.json` 且 daemon 主循环下一轮扫描拾取
- **THEN** 主循环将该请求投递到后台队列并在本扫描周期内继续后续工作（总耗时不超过一个扫描周期）
- **THEN** 处置在后台线程启动，pending disposition 在后台线程内于执行前落盘

#### Scenario: 处置运行期间主循环不停摆

- **WHEN** 一个 Administrator 处置正在后台执行（实测可达数分钟）
- **THEN** 主循环仍以 1s 粒度继续 SPEC 派发、admin_monitor 巡检与后续请求拾取
- **THEN** 处置期间到达的新 invoke 请求被拾取入队，不丢失、不覆盖

#### Scenario: 处置串行执行

- **WHEN** 队列中存在多个待处理的 invoke 请求
- **THEN** 同一时刻最多一个 Administrator run 在执行，请求按到达顺序（先到先得）逐个处理
- **THEN** 单个 Administrator run 结束后（含落 final disposition），队列中的下一个请求才被启动

#### Scenario: 后台处置失败不丢痕

- **WHEN** 后台线程中的处置抛出异常（agent_runner 异常、写入失败等）
- **THEN** 按 `invoke_manual` 既有语义落 failed disposition 与升级告警（记录不因移入后台而丢失）
- **THEN** 后台工作线程本身不因单次处置异常退出，继续处理队列中的后续请求
