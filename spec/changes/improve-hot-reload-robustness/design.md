# Design: improve-hot-reload-robustness

## Context

- 配置校验为 plain dict + 手写白名单（非 pydantic）。`core/config.py:71`
  `KNOWN_AGENT_TYPES`，`core/config.py:388-393` `_validate_agent_models` 对未知键
  `raise ValueError`——全库唯一"键集不匹配→整段拒绝"残留点。
- 热重载链路：`fenixd.py:238-244` 每 30s 调 `_maybe_reload_config`
  （`fenixd.py:290-316`）→ `ConfigLoader.resolve_config_into`（`config.py:127-136`，
  clear/update 原子，失败零触碰）。失败时 `_config_snapshot` 不更新 → 每 30s 重试重报
  （09-04 实证恰好 50 条 = 25min ÷ 30s）。
- 启动与热重载共用 `resolve_config` → `_validate` 路径；启动失败 FATAL exit(1)，
  且 Logger 在配置加载之后才初始化（`fenixd.py:86-88`），启动期错误只落 stderr。
- 告警链路：`core/admin_monitor.py:510-533` `_detect_daemon_errors` 取日志尾部 200 行，
  从尾往回数 `"level": "ERROR"`，遇其他级别即断，`streak ≥ DAEMON_ERROR_THRESHOLD(=3,
  :36 写死)` 触发 critical。巡检周期 `max(admin.interval_minutes, 0.5)` 默认 5 分钟
  （`config.py:629`）。09-04 事故：02:36:24 第 2 次复现已成立但活跃期被 INFO 打断
  看不见；02:41:56 后日志安静、ERROR 物理堆积；02:45:23 巡检撞上连续 6 条才触发。
- 运行时兜底：`get_agent_model_assignment`（`config.py:441-491`）无白名单，链缺失返回
  None → `runner.py:1096-1101` 走默认网关（cc-switch）。
- 同仓库正确先例：`normalize_timeout_overrides`（`config.py:771-817`）未知键逐键
  ERROR+忽略+其余生效；未知 provider 名校验（`config.py:416-424`）ERROR 不阻塞。
- 现成版本指纹参照：`.fenix/daemon_started`（supervisor 每次启动写 UTC 时间戳）；
  全库无 git hash 捕获、无 schema 版本号。

## Goals / Non-Goals

**Goals:**

1. 未知 agent 类型键不再使热重载/启动整段失败；降级告警自带重启处方，把"25 分钟
   只在 logs 里的断层"变成可行动提示。
2. 检测"磁盘代码 vs 进程内代码"不一致，主动提示重启。
3. daemon_errors 升级口径与错误复现率挂钩，消除"看日志安静度运气"的触发机理，
   无人介入窗口从 9.5 分钟缩到最坏 ~5 分钟。
4. 以上均不放大告警噪音（cooldown 节流保持），不新增配置键。

**Non-Goals:**

- 不做 1s 粒度快速通道检测（二期可选增强，需评审并发唤起路径）。
- 不改 15 分钟 cooldown、`HUMAN_SEVERITIES`、合成兜底静默化等降噪体系。
- 不做配置 schema 版本号机制（依赖人工 bump 纪律，必然腐化）。
- 不改 Dashboard 设置页与 `AgentModelPanel.tsx`（角色表与白名单的手动同步问题
  超出本次范围）。
- 不动 `agents.models` 之外其他段的结构性校验语义。

## Decisions

**D1 — 未知键降级为"跳过校验、保留键、逐键告警"，不剔除键。**
跳过 = 不校验该键形态，但键留在有效配置中：新代码派发该角色时运行时解析正常生效
（`get_agent_model_assignment` 无白名单）；旧代码根本不派发该角色，键惰性。两种情况
都无崩溃路径，不产生"配置不完整"。备选"从配置剔除未知键"被否：会产生嵌套剔除机制
的复杂度，且旧代码进程剔除后、新代码进程反而丢失配置（跨重启不一致）。告警级别从众
用 ERROR（与 `config.py:421`、`config.py:779` 先例一致），任务原文的 WARNING 不强制；
关键是**非阻塞 + 文案内嵌 `touch .fenix/restart_request` 处方**。

**D2 — 分类线：键集不匹配（代码演进产物）→ 逐键降级；值/类型非法（配置真坏）→
整段拒绝。** 已知键的形态错误（provider 链非法）仍 raise——这不是"键新"，是"值坏"。
`agents.models` 整段非 dict 从 raise 降为"忽略该段 + ERROR"（无法逐键时按段跳，
对齐 `_load_optional_yaml` 哲学）。`llm.providers` 非 list 等其他结构性 raise 不动。

**D3 — 去重策略：同一未知键每进程生命周期只报一次。** 模块级已告警键集合
（仿 `config.py:40-41` `_DEPRECATED_STUCK_WARNED` 模式）。热重载失败快照不更新
的 30s 重试风暴下，不去重则告警与 ERROR 同步刷屏；去重后重试期间静默跳过。
keys 以键名字符串为准（不随进程内白名单变化失效）。

**D4 — 陈旧检测用代码 mtime 指纹，不用 git hash / schema 版本。** `initialize()`
一次性 glob `fenixd.py + core/**/*.py` 缓存文件列表并取 max st_mtime_ns 为 baseline；
`_maybe_reload_config` 每轮做 ~60 次 stat，代价可忽略。超 baseline → 每进程一次
WARNING。mtime 覆盖 rsync/patch/checkout/未提交修改，worktree 友好；git rev-parse
覆盖不了未提交修改且怕非 git 环境；schema 版本号靠人工纪律必腐化。误报面仅
"touch 无内容变化"，可接受。检测函数提取为纯函数（`code_files_changed_since`
形态）便于单测。

**D5 — daemon_errors 升级口径：10 分钟窗口内同指纹 ≥2 次且相邻间隔 ≤5 分钟。**
无状态每轮巡检重算（读尾部即得），不持久化计数器、重启安全、恢复靠窗口滑动自然
过期（重载成功不写 ERROR，10 分钟后自动归零）。防抖评估：单次瞬时=1 次不触发；
两条不同错误各 1 次不触发；相隔 >5 分钟的孤立抖动不触发——"第 2 次+间隔约束"
已足够防抖，提高到 3 只会重演本次滞后。

**D6 — 指纹 = sha1(component + "\x00" + normalize(message))，归一化保守集。**
ISO 8601 时间戳→`@`、UUID→`~`、≥16 位 hex→`~`、纯数字序列→`#`；不动路径与文字
骨架——过度归一化会把不同错误误聚合，而"≥2 次才升级"已提供缓冲。本事故 message
全等（变量在独立 timestamp 字段）天然命中；归一化主要覆盖 message 内嵌变量
（run_id、attempt 计数、路径时间戳）的泛化。逐行 JSON 解析（logger 保证单行 JSON、
`\n` 已转义，多行 traceback 安全）；非 JSON 行回退 raw 行归一化；timestamp 缺失行
fail-closed（仍计入桶，间隔按满足）——生产 logger 恒有 timestamp，此分支只影响
旧格式/fixture，方向宁可多告警不漏告警。

**D7 — 阈值全部保持模块常量，不进 config。** 窗口 10min / 间隔 5min / 次数 2 于
`admin_monitor.py:36` 附近定义，与既有 `DAEMON_ERROR_THRESHOLD` 风格一致，规避
"新增配置项必须带 Dashboard UI"约束。

**D8 — 启动行为变更接受为统一宽容。** 启动与热重载共用 `_validate`，不引入
双模式参数：未知键启动不再 FATAL（崩溃不能帮用户改 typo，只会让 daemon 起不来），
值类错误仍 FATAL。启动期 `_logger` 输出只到 stderr（Logger 初始化在配置加载后），
接受现状不为此搬动 Logger 初始化顺序。

**D9 — 顺带清理：`config.py:134` 的二次 `_validate` 调用为死代码**
（`resolve_config` 内部 `config.py:123` 已校验同一份 fresh），删除。

## Risks / Trade-offs

- [降级后未知键静默存在，用户可能长期不重启，模型分配不生效] → 降级告警内嵌重启
  处方 + 陈旧检测 WARNING 双通道提示；且"键保留在配置中"意味着重启后立即生效，
  无需任何迁移。
- [归一化过宽导致异类错误被误聚合、一次告警掩盖多因] → 保守集只归一化时间戳/UUID/
  hex/纯数字四类；"≥2 次+间隔 ≤5min"进一步约束；测试用例锁定异类不聚合。
- [mtime 指纹在 touch 无内容变化时误报一次 WARNING] → 每进程仅一次，噪音可控。
- [告警口径改后触发频率上升（原口径下活跃期永不触发）] → 15 分钟 cooldown 节流
  兜底；升级条件本身要求复现 ≥2 次，单发瞬时错误不触发。
- [启动宽容后配置 typo 长期潜伏] → 值类错误仍 FATAL 拦住主要 typo 面；键集 typo
  （把 implementer 拼错）会被降级告警点名，且 Dashboard 侧 `write_config` 校验
  仍用新白名单拒绝保存，入口已挡。

## Migration Plan

单进程内行为变更，无数据迁移、无配置迁移。合并后按惯例 `touch .fenix/restart_request`
重启 daemon 生效。回滚 = revert 提交再重启。

## Open Questions

（无——执行模式 full，验收以 specs/ 两能力 Scenario 为准）
