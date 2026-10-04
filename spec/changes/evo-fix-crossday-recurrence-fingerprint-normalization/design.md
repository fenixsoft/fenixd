# fix-crossday-recurrence-fingerprint-normalization 设计

## Context

_detect_crossday_recurrence（core/admin_monitor.py:3081-3129）为 evo-add-codefix-conn-error-cooldown 任务 3.1 落地（10-02 19:39Z 入 main，merge 5dcf0666），设计见该 spec design.md D6（「4 天样本时刻差 <2 秒，容差充裕」）。但它依赖的错误指纹由 _normalize_error_message/_error_fingerprint（:564-585）生成，其中 _STANDALONE_NUMBER_RE（:561，负向先行 (?<![0-9a-zA-Z_])\d+(?![0-9a-zA-Z_])）对 "23.4s" 只归一整数 23 为 #、尾数 .4 因后跟单位字母 s 而保留——延迟数值不同的同形死亡行指纹必然不同（实测：dbd8dc91f1530046 vs 2770ed6f532f254c）。记忆载体 _daemon_fp_last_failure（:1046 附近）是实例内存；跨重启回退 _read_tail_error_entries（:3257）只读 _TAIL_ERROR_READ_BYTES=256KB（:589）尾窗。daemon 10-02 22:48:40Z 重启（supervisor.log:2485）落在两夜窗口之间，回退窗内无前夜条目。该机制落地以来实弹命中为零。

## Goals / Non-Goals

- Goals：同形夜间死亡行（仅延迟数值不同）指纹一致；跨日记忆跨 daemon 重启存活；回退对账覆盖 ≥24h。
- Non-Goals：不改 daemon_errors 第一维度判定与熔断/冷却/salvage 行为；不做告警 store 的结构化指纹落库（docstring :3137 已声明 store 无指纹字段，本能力以日志为对账源）；不处置上游窗口本身。

## Decisions

### D1：归一化补正则级缺陷（主修）
在 _normalize_error_message 中为「\d+\.\d+ 单位字母」形态（时间/秒数类）增加归一规则（整体替换为占位符，如 #s），优先于现有整数规则；补单测用 10-02/10-03 两夜真实死亡行文本（仅换延迟数值）断言指纹相等。备选方案（api_timeout 死亡改结构化签名：api_timeout 布尔 + stderr_tail 骨架哈希）作为实现者可选路径——若选此路径须保证与既有指纹空间不串扰（前缀命名空间区分）。

### D2：记忆持久化仿既有状态文件形态
指纹记忆写入 .fenix/ 下小状态文件（仿 fix-progress.json / admin_infra_breaker.json 既有形态：原子写 + 锁），加载失败降级为纯日志回退。注意与「告警 store 无结构化指纹字段」现状解耦：状态文件是观测私有记忆，不是台账。

### D3：回退检索定向化
无记忆时回退不扫全量日志、也不扫 24h 全窗：以本轮扫描得到的同签名最新时刻 last_ts 为锚，按 last_ts − 24h ± 容差（DAEMON_ERROR_CROSSDAY_PERIOD/TOLERANCE_SECONDS）构造窄时间窗，先按日期文件/行前缀（fenixd.log.N 轮转）缩小范围再 grep 同签名死亡 ERROR 行，替代 256KB 尾读；检索成本与命中留痕写 debug 日志。tasks 2.2「可回溯 ≥24h」指该定向窗的覆盖能力上限，非全窗扫描。

### D4：保持只读边界
聚合触发仅走既有 escalation 升级通道（绕过已知指纹冷却的既有行为保留），不接派发/熔断/冷却任何消费点；daemon_errors 第一维度（≥2 次/10 分钟）判定代码不动。

## Risks / Trade-offs

- 归一化放宽可能聚合同刻不同根因：占位符仅限「数字.数字+单位字母」形态且指纹其余部分须全等，误聚面极小；第一维度判定不受影响。
- 状态文件增长：仅存「签名→上次时刻」映射且按窗口淘汰，体量常数级。
- 定向 grep 的 IO 成本：仅在重启后首轮扫描触发一次，非每轮。
- 第一维度计数输入随归一化放宽而变：by_fp 同喂第一维度与跨日检测（admin_monitor.py:3020-3034），同形行聚合计数只增不减（不减少既有告警，方向保守）；合并后指纹值改变使已冷却指纹 fp[:8] 前缀对账（_daemon_fp_known，:3131）一次性失配——部署后首个重启冷却窗内可能多升级一次，一次性效应。
- 归一化范围仅「数字.数字+单位字母」：整数+单位形态（如 "4s"）在既有 _STANDALONE_NUMBER_RE 规则下同样不归一（尾数后跟单位字母被保留），同形不同值的整数延迟行指纹依旧不等；本 SPEC 不处置，留待按实测误聚/漏聚数据决定是否扩大占位符范围。

## Migration Plan

单 commit 落地归一化补丁 + 持久化 + 回退检索 + 测试；重启 daemon 生效；无历史数据迁移（首夜记忆从日志回退检索重建）。

## Open Questions

- 无。