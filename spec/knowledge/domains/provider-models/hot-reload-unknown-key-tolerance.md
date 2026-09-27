<!-- knowledge: capability=hot-reload-unknown-key-tolerance rev=1 sources=spec/archive/2026-09-11-improve-hot-reload-robustness -->

# 配置热更新未知键容错

配置校验对「本进程不认识的 agent 类型键」逐键降级而非整段拒绝；值类错误维持整段拒绝与原子保留。

## 规则

- 配置校验（启动与热重载共用路径）遇到 `agents.models` 中本进程白名单之外的 agent 类型键时逐键降级：发一条降级告警并跳过该键校验，其余键照常校验、其余配置段照常应用；未知键保留在有效配置中（跳过校验 ≠ 剔除数据）。
- 值类错误不被未知键降级掩盖：已知键形态非法（如 provider 链非法）时校验仍整段拒绝；降级仅适用于键集不匹配。
- 降级告警为非阻塞级别（非异常抛出），文案必须同时含未知键名、本进程已知类型列表、重启处方 `touch .fenix/restart_request`；同一未知键在进程生命周期内去重（热重载失败重试期间不逐轮刷屏）。
- 运行时解析不引入白名单：`get_agent_model_assignment` 无白名单检查，白名单仅存在于配置校验层；链缺失时走默认网关的既有兜底行为不变。
- 结构性/类型错误（如 `llm.providers` 非 list）维持 raise → 整段拒绝；失败时当前生效配置逐键不变（原子保留）。`agents.models` 整段非 dict 时按「忽略该段 + 告警」处理，其余段的结构性 raise 不变。
- 启动与热重载统一宽容：未知 agent 类型键不导致启动 FATAL（降级告警落 stderr 或日志可见）；值类错误维持启动失败。
- 代码陈旧检测：daemon 在 `initialize()` 记录代码 mtime 指纹 baseline（fenixd.py + `core/**/*.py` 的最大 st_mtime_ns）；热重载检测点发现磁盘代码 mtime 超过 baseline 时打「磁盘代码较进程启动时已更新，进程内校验规则可能为旧版，建议重启」WARNING，每进程生命周期至多一次。

## 溯源

- 2026-09-11 improve-hot-reload-robustness — 建立未知 agent 类型键逐键降级与告警三要素、值类错误整段拒绝与原子保留、启动热重载统一宽容、磁盘代码陈旧检测告警
