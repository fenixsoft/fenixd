# 提案：repair 车道凭据探针修复

## 背景

fenixd 框架的 repair/arbiter 回落车道自 2026-11-16 起持续 unhealthy 9 天：车道前置探针（lane_preflight）以「daemon 进程环境无 ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY 路由痕迹」判定回落链凭据不可判定，回落冻结闸据此拦截一切 repair/arbiter 回落派发。告警 lane_env_unavailable 现条目（fenix-desktop 台账 e6969021fea3）自 11-22 起挂账 62.1 小时未收口，探针 WARNING 以每分钟 2 条刷屏 8000 余条。核查确认根因可落地修复：daemon 进程环境确无 ANTHROPIC_* 键（/proc 直读），而用户级 provider 配置 agents.models 13 个角色与病灶项目 fenix-desktop 项目级 11 个角色唯独漏配 repair（arbiter 已配显式链且由此转 healthy；fenixd 与 dsh-plugins 项目级 agents.models 为空，repair 同无显式链）；同时探针为纯本地判定、无试呼路径，告警话术「无需人工处置」与超时无升级通道形成死锁。fenix-desktop 与 dsh-plugins 两项目同病，连续四日 todo 挂账零修复动作。

## 问题

1. 凭据供给缺口：repair 角色在两级 provider 配置中均无显式链，daemon 进程环境亦无 ANTHROPIC_* 注入——回落链凭据不可判定为真，非探针误判主导；systemd.env 承载机制已存在（fenixd.py 幂等写入、denylist 不拦 ANTHROPIC_*、fenixd 项目 daemon 已有 10 个 ANTHROPIC_* 键活体先例）但 repair 侧未接入。
2. 探针判定缺口：lane_preflight.py 明文「纯本地检查不发 API 请求」，OAuth/CLI 默认档形态下永久 indeterminable，无取证路径裁决「实际可用与否」。
3. 告警面缺口：「随恢复自动关闭、无需人工处置」话术硬编码，超 24 小时未恢复时无任何人工升级改发（现有 24 小时 aging 仅出现在每日自省报告文本行），无人值守形态下形成挂账死锁。

## 目标

- repair 回落链凭据可判定：经 .fenix/systemd.env 注入 ANTHROPIC_* 凭据，探针转 healthy、回落冻结闸解除。
- 探针获得取证能力：env 嗅探不可判定时按 TTL 降级试呼一次 CLI 短请求，以实测裁决默认档可用性。
- 告警不再劝退人工：挂账超 24 小时的话术切换为「需人工升级」。

## 非目标

- 回落派发闸机制本身的重构（evo-provider-fallback-dispatch-gate 承接）。
- 逐角色 provider 配置巡检/自动补配（本次仅修 repair 侧）。