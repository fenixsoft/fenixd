# design：fix-transient-break-unseal-backoff

## Context

- 熔断器：core/agent_runner/provider_circuit.py ProviderCircuit——record_transient_error（:521）按归一化指纹（:488，剥 model 名/时间戳/长数字串）记 _transient_break_events 滑窗，达阈值置 _transient_break_until 并 ERROR+告警；冻结闸门消费在 core/pm_engine/dispatch/queue.py:388（_process_queue 首道闸，冻结期整队 hold）。
- 解封：is_global_transient_break 到期分支（:665-698）清零+WARNING+_wake_dispatch_after_break（:700-728 直接 _process_queue 一次性放全）+_auto_resolve_transient_storm；无任何解封后状态。
- 事发现场（2026-09-22）：两场风暴 fenixd.log:7060/:7180，解封 :7123 后 35.9 秒再吃失败、16 分 34 秒第二场；per-spec 600s 延迟（backoff.py:224-260）在冻结期内耗完，解封瞬间两 SPEC 积压同批放出。
- 可对齐先例：per-provider 4xx 熔断 half_open 探针（provider_circuit.py:152-160 注释）；队列优先级与 aging（queue.py:63/:209）。
- 测试锁定面：tests/test_transient_backoff.py:780（test_break_expires_and_resets）、:858/:872（解封立即唤醒/wake 失败不阻塞恢复）。
- 配置：core/config.py:169-172 常量与 :263-295 get_transient_config 规范化；现场 .fenix/config.yaml:129-133（threshold 5、window/cooldown 600）。

## Goals / Non-Goals

**Goals**

1. 解封后积压不再同拍全量重撞 provider：渐进 hold + 单条探针 + 按优先级错峰。
2. 解封次数有记忆且稳定后衰减，避免 provider 长时间抖动时反复全额重蹈。
3. 既有三层退避与熔断保护语义零变化。

**Non-Goals**

1. 不改熔断触发条件/滑窗/冻结期（threshold/window/cooldown 保持）。
2. 不做派发前主动 LLM 健康探测（add-impl-selfcheck-model-probe design 明确不做，本 SPEC 同样不做）。
3. 不改 per-provider 4xx 熔断与告警链路。

## 设计决策

- **D1｜渐进 hold 与探针二选一改为叠加**：todo 给了两个可选项；二者不冲突——hold 解决「解封瞬间仍是故障窗」的等价重试，探针解决「积压全量放出的并发重撞」，叠加后探针天然成为 hold 期满后的第一个放行对象，实现为同一段放行逻辑的两种粒度（首条=探针、其余=批量）。
- **D2｜解封次数按指纹记忆、稳定衰减**：状态挂在 ProviderCircuit 的 per-fingerprint 字典上（与 _transient_break_events 同生命周期管理），稳定窗（缺省 30 分钟无新熔断）后次数减一而非直接清零，既防长期抖动升级又防一次性事故永久惩罚；daemon 重启即清零（可接受：重启本身拉开了重试间隔）。
- **D3｜放行复用 _process_queue 单通道**：hold 状态由 is_global_transient_break 同源的判定函数扩展（如 is_post_unseal_hold），queue.py:388 首道闸同时消费冻结与 hold 两态，放行仍走 _process_queue（首条探针=只弹出一条的受限调用），不新增派发通道，避免双通道竞态。
- **D4｜观察窗探针判定复用记账**：探针是否「通过」不引入新探测调用——探针 run 的 attempt 若再入 _append_transient_event 记账即判失败，天然复用现有滑窗，无需心跳式探测。
- **D5｜缺省启用但保守**：基数 60 秒、封顶 600 秒、观察窗 120 秒、稳定窗 30 分钟（均可配）；对照事发现场，第二场风暴会在 hold=120 秒+探针后才开始放行，大部分积压错开故障窗。

## 风险

- 恢复时延变长（最长 hold 封顶 600 秒+探针观察窗）：对照收益（避免 16 次白烧 attempt 与两场 21 分钟全局停摆）可接受，且配置可调。
- 探针恰逢故障持续时多烧一次 attempt：单条成本，远低于现状的全量重蹈。
- 既有测试语义修订遗漏：D4 清单点名 :780/:858/:872，任务书单列修订项。
