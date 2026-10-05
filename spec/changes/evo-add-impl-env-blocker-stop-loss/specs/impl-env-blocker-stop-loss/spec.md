## ADDED Requirements

### Requirement: 环境阻塞任务止损

implementer 提示词约束：任一环境依赖在同一 run 内连续 ≥3 次失败尝试（按尝试次数计，不按错误签名）即冻结该任务——design 有 fallback 条款先走 fallback，否则将该任务登记为 unfinished 并转 partial 继续其余任务；MUST NOT 在 run 内为救单个验证场景对宿主做内核级/镜像级不可逆改造（内核模块替换、系统镜像降级等）。

#### Scenario: 连续失败触发冻结

- **WHEN** 同一环境依赖连续第 3 次失败尝试
- **THEN** 该任务被冻结，run 转 fallback 路径或登记 unfinished 后继续其余任务

#### Scenario: 禁止宿主级改造救场景

- **WHEN** 实现者为使单个验证场景通过而准备替换内核模块或降级系统镜像
- **THEN** 该动作被提示词约束禁止，环境缺口走 env 升级或环境供给层

### Requirement: 任务进度停滞观测

框架对 impl run 维护「自最近一次 run 内任务完成起的轮数」计数（数据源为 run 流内 TaskUpdate 观测，非主树 tasks.md），超过配置阈值时在 run_metrics 注记并打 WARNING；该观测不参与续期/击杀判定。

#### Scenario: 长时间无任务完成触发预警

- **WHEN** impl run 连续 N 轮（默认 200，可配）无任何任务完成
- **THEN** run_metrics 附加停滞注记并打 WARNING 日志，run 继续正常执行