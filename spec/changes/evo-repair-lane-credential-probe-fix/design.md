# 设计：repair 车道凭据探针修复

## 现状结构

- 探针判定：core/agent_runner/lane_preflight.py:109 probe_default_chain_credentials → :139-145 os.environ 三键嗅探（全空即 indeterminable）；:113-114「纯本地检查不发 API 请求」、:165「MUST NOT 真发 API 请求」为既有设计约束。
- 告警面：:365-404 ensure_lane_env_alert（append_if_absent 单发去重，:397-400 话术含「无需人工处置」）；:416-446 resolve_lane_env_alert（唯一关闭条件=探针转 healthy）。
- 周期消费：fenixd.py:1246-1264 每 60 秒周期 tick；:1167-1198 unhealthy→WARNING+告警、healthy→自动关闭。
- 凭据承载：fenixd.py:972-1062 systemd.env 幂等写入机制；core/systemd_hosting.py:87-93 denylist（CLAUDE_*/AI_AGENT 等前缀，ANTHROPIC_* 不在列）；fenixd 项目 daemon 进程环境 10 个 ANTHROPIC_* 键为活体先例。
- 超时升级现状：core/self_review.py:250 UNHANDLED_ESCALATION_AGING_HOURS=24 仅渲染自省报告文本行，无独立通道。

## 设计决策

1. 止血走既有 systemd.env 通道：不新造注入机制，向项目 .fenix/systemd.env 追加 ANTHROPIC_* 两键（对齐工作车道 bigmodel.cn 链），denylist 已放行、活体先例已验证，属配置动作。
2. 试呼走 TTL 降级而非周期试呼：env 嗅探 indeterminable 才试呼、30 分钟 TTL 缓存、一次最小成本 CLI 短请求——保住「探针默认纯本地、不烧钱不触发限流」的原设计意图，同时补上取证路径。
3. 话术条件化不改告警结构：在 ensure_lane_env_alert 内按同 dedup_key 既有告警的 created 年龄切换 recommended_action 文案，复用 24 小时口径，不新增告警类型、不新增通道。

## 风险

- 试呼本身消耗少量 token 并可能与工作负载争限流配额——TTL 缓存 + 仅 indeterminable 时触发，把频率压到每 30 分钟至多一次。
- systemd 重载依赖宿主 systemd 单元实际引用该 env 稿（fenix-desktop 已实测 HOME/USER 生效，本机引用在位）；其他项目若未提升 env 稿则止血项不生效——验收以 /proc/<pid>/environ 出现 ANTHROPIC_* 为准，未生效项目回退为探针 unhealthy 话术提示。