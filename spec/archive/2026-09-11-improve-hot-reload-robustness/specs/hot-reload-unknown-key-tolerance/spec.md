# hot-reload-unknown-key-tolerance 增量规格

## ADDED Requirements

### Requirement: 未知 agent 类型键逐键降级

配置校验（启动与热重载共用路径）遇到 `agents.models` 中本进程白名单之外的
agent 类型键时 MUST NOT 拒绝整段配置：MUST 发出一条降级告警并跳过该键的校验，
其余键照常校验、其余配置段照常应用。未知键 MUST 保留在有效配置中（跳过校验
≠ 剔除数据）。

#### Scenario: 未知键与其余配置共存
- **WHEN** 热重载配置含 `agents.models['fast-track']`（进程白名单不含该键）
  且含合法的 `implementer` 分配
- **THEN** 热重载成功、`implementer` 分配完整生效、日志出现含键名的降级告警

#### Scenario: 已知键的值类错误不被未知键降级掩盖
- **WHEN** `agents.models` 同时含未知键与形态非法的已知键（如 provider 链非法）
- **THEN** 校验仍然整段拒绝（值类错误语义不变），降级仅适用于键集不匹配

### Requirement: 降级告警内容与重启处方

降级告警 MUST 为非阻塞级别（WARNING 或 ERROR，实现自选但 MUST 非异常抛出），
文案 MUST 同时包含：未知键名、本进程已知类型列表、重启处方
（`touch .fenix/restart_request`）。同一未知键在连续多轮热重载重试期间 MUST
去重（不逐轮重复刷屏）。

#### Scenario: 告警三要素
- **WHEN** 任一次配置校验触发未知键降级
- **THEN** 告警文案同时含未知键名、已知类型列表与 `touch .fenix/restart_request`

#### Scenario: 重试期间不逐轮重复
- **WHEN** 热重载失败快照不更新导致每 30 秒重试、每轮都命中同一未知键
- **THEN** 该键的降级告警在进程生命周期内对同一键只报一次（后续轮次静默跳过）

### Requirement: 未知键运行时惰性与解析兼容

降级 MUST NOT 把未知键从有效配置剔除；运行时模型分配解析
（`get_agent_model_assignment`）MUST NOT 引入白名单检查——白名单仅存在于
配置校验层。链缺失时走默认网关的既有兜底行为不变。

#### Scenario: 新代码进程正常解析保留键
- **WHEN** 进程白名单含 `fast-track` 且有效配置含 `fast-track` 分配
- **THEN** `get_agent_model_assignment('fast-track')` 正常返回该分配

#### Scenario: 旧代码进程派发兜底不变
- **WHEN** 有效配置含进程白名单之外的键且该角色仍被派发、链缺失
- **THEN** 运行时按常规解析返回空链走默认网关兜底（现行为不变，无白名单拦截）

### Requirement: 值类错误维持整段拒绝与原子保留

结构性/类型错误（如 `llm.providers` 非 list）MUST 维持 raise → 整段拒绝；
失败时当前生效配置 MUST 逐键不变（原子保留语义回归锁）。`agents.models`
整段非 dict 时 MUST 按"忽略该段 + 告警"处理（对齐 `_load_optional_yaml`
哲学），其余段的结构性 raise 不动。

#### Scenario: 值类非法原子保留
- **WHEN** 热重载遇 `llm.providers` 非 list
- **THEN** 抛异常、热重载失败、当前生效配置逐键不变

#### Scenario: models 段形态坏按段降级
- **WHEN** `agents.models` 为非 dict 值（如 list）
- **THEN** 不抛异常，该段被忽略并告警，其余段照常校验应用

### Requirement: 启动与热重载统一宽容

启动期校验 MUST 与热重载使用同一未知键容忍语义：未知 agent 类型键 MUST NOT
导致启动 FATAL 退出；值类错误 MUST 维持启动失败。启动期告警 MUST 可见
（落 stderr 或日志文件均可）。

#### Scenario: 启动容忍未知键
- **WHEN** daemon 启动时配置含未知 agent 类型键
- **THEN** 启动继续（非 FATAL），降级告警可见

#### Scenario: 启动仍拒绝值类错误
- **WHEN** 启动时配置 `llm.providers` 非 list
- **THEN** 启动失败（FATAL），行为与现状一致

### Requirement: 代码陈旧检测

daemon MUST 在 `initialize()` 记录代码 mtime 指纹 baseline
（fenixd.py + core/**/*.py 的最大 st_mtime_ns）；热重载检测点发现磁盘代码
mtime 超过 baseline 时 MUST 打印一条"磁盘代码较进程启动时已更新，进程内校验
规则可能为旧版，建议重启"类 WARNING，且每进程生命周期最多一次。

#### Scenario: 磁盘代码更新提示
- **WHEN** daemon 启动后 `core/` 下代码文件被更新、随后触发热重载检测
- **THEN** 打印一条陈旧代码 WARNING，同进程内不重复

#### Scenario: 无变更不告警
- **WHEN** 所有受跟踪代码文件的 mtime 均未超过 baseline
- **THEN** 不出现陈旧告警
