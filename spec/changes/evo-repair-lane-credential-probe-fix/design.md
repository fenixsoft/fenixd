# 设计：repair 车道凭据探针修复

## 现状结构

- 探针判定：core/agent_runner/lane_preflight.py:109 probe_default_chain_credentials → :143-149 os.environ 三键嗅探（全空即 indeterminable）；:112-114「纯本地检查不发 API 请求」、:172「MUST NOT 真发 API 请求」（后者语境为②级显式链本地解析）为既有设计约束。
- 告警面：:384 ensure_lane_env_alert（append_if_absent 单发去重，:416-420 话术含「无需人工处置」）；:435 resolve_lane_env_alert（唯一关闭条件=探针转 healthy）。
- 周期消费：fenixd.py:1347-1364 _lane_preflight_periodic_tick 每 60 秒周期 tick（:1357 时间门）；:1270-1330 _lane_preflight_consume unhealthy→WARNING+告警、healthy→自动关闭；启动自检 :1342 同探针。
- 回落冻结闸（试呼第三类消费方）：runner.py:7017 PROVIDER_FALLBACK_GATE_TTL_S=300s，:7068 闸自持 LanePreflightCache，TTL 过期 get_or_probe 同步重探，verdict 非 ok 即冻结回落派发、ok 放行解冻。
- 凭据承载：fenixd.py:1033 .fenix/systemd.env 在场性检查与 PATH 行幂等原子追加先例；core/systemd_hosting.py:90-97 denylist（CLAUDE_*/AI_AGENT 等前缀，ANTHROPIC_* 不在列）；fenixd 项目 .fenix/systemd.env 已有 10 个 ANTHROPIC_* 键活体在位；fenix-desktop env 稿在场但 0 个 ANTHROPIC 键、dsh-plugins env 稿缺席（2026-11-27 实测）。
- 超时升级现状：core/self_review.py:259 UNHANDLED_ESCALATION_AGING_HOURS=24 仅渲染自省报告文本行，无独立通道。

## 设计决策

1. 止血走既有 systemd.env 通道：不新造注入机制，向项目 .fenix/systemd.env 追加 ANTHROPIC_* 两键（对齐工作车道 bigmodel.cn 链），denylist 已放行、活体先例已验证，属配置动作。
2. 试呼走 TTL 降级而非周期试呼：env 嗅探 indeterminable 才试呼、30 分钟 TTL 缓存、一次最小成本 CLI 短请求——保住「探针默认纯本地、不烧钱不触发限流」的原设计意图，同时补上取证路径。约束：试呼 TTL 缓存 MUST 为进程级共享单例（模块级）——试呼内联在 probe_default_chain_credentials 内即可被三类消费方共享（回落冻结闸 runner.py:7068 自持缓存 300s 重探、daemon 60s 周期 tick fenixd.py:1362、启动自检 fenixd.py:1342，三者各持独立 LanePreflightCache，试呼缓存若随各自实例走则闸节拍使试呼频率 6 倍于设计意图）；试呼 MUST 带短超时（复用 PROBE_HEALTH_TIMEOUT_S 口径），超时/异常按 unhealthy fail-open（evidence 附错误尾部），不无界阻塞冻结闸派发入口。
3. 话术条件化不改告警结构：在 ensure_lane_env_alert 内按同 dedup_key 既有告警的 created 年龄切换 recommended_action 文案（append_if_absent 单发语义命中在案条目零写跳过、不更新既有条目——切换须按 dedup_key 定位未处理条目经 AdminStore update 就地改写，幂等），复用 24 小时口径，不新增告警类型、不新增通道。

## 风险

- 试呼本身消耗少量 token 并可能与工作负载争限流配额——TTL 缓存 + 仅 indeterminable 时触发，把频率压到每 30 分钟至多一次。
- systemd 重载依赖宿主 systemd 单元实际引用该 env 稿（fenix-desktop 已实测 HOME/USER 生效，本机引用在位）；dsh-plugins 尚无 env 稿、fenixd 已有 10 键活体——未提升 env 稿的项目止血项不生效，验收以 /proc/<pid>/environ 出现 ANTHROPIC_* 为准，未生效项目回退为探针 unhealthy 话术提示。