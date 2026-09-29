<!-- knowledge: capability=admin-health-monitor rev=1 sources=spec/archive/2026-09-02-add-administrator-agent -->

# 管理员健康监视器

daemon 侧零 LLM 成本的周期性困境检测（AdminMonitor），是唤起 Administrator 的信号源。

## 现行规则

- 存在进行中 spec（implementing/testing）时，按 `admin.interval_minutes`（默认 5）周期运行轻量健康检查；检查仅基于本地数据（STATE.md、`.fenix/runs/` 转录、`fenixd.log`），不调用任何 LLM。
- 检测项包括：同一 spec 短时间窗口内重复失败（失败 run 数超阈值）、spec 状态抖动（ready↔implementing 快速切换）、spec 卡死（implementing/testing 超过 stuck 阈值且无 run 进度）、重复 merge-back 失败（`_merge_streak` 达熔断阈值仍停留）、daemon 日志中的连续 ERROR。
- 卡死阈值由 `agents.run_timeout_seconds` 单源派生（`effective_stuck_threshold_seconds`）；已弃用的 `schedule/admin.stuck_threshold_minutes` 配置键不论是否配置都不影响结果，检测到即告警。
- blocked_stuck 检测对冻结类 blocked 豁免：人工冻结等「人该等」的停摆不打扰 Administrator，豁免按结构化 `frozen` 标记识别。
- 检出困境信号即触发 Administrator 唤起；所有进行中 spec 运行正常时仅更新最后检查时间戳，不唤起任何 Agent、零 LLM 成本。
- 降噪节流：同一 spec 的同一类信号在 `admin.escalation_cooldown_minutes`（默认 60）内只唤起一次 Administrator，第二次仅记录、跳过唤起，避免反复唤起烧钱。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：AdminMonitor 周期巡检含 blocked_stuck 检测；人工冻结对 blocked_stuck 豁免，豁免按结构化 frozen 标记识别
- [2026-09-02 add-administrator-agent](spec/archive/2026-09-02-add-administrator-agent/) — 固化周期检测契约：本地数据零 LLM 检测项清单（重复失败/状态抖动/卡死/merge 反复失败/连续 ERROR）与同信号冷却节流
