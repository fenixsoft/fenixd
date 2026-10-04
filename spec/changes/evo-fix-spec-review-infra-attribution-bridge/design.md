# fix-spec-review-infra-attribution-bridge 设计

## Context

spec_review 车道已有完整防护骨架：_classify_run_failure 三分（core/pm_engine/spec_review.py:1144-1202，_INFRA_FINGERPRINTS :70-79 含 "rate limit"、_NUMERIC_INFRA_RE :102 含 429）、infra 分支不递增 _review_attempts（:1243-1270，MAX_REVIEW_ATTEMPTS=3 :32）、dispatch_review 入口熔断短路（:230-245，infra_breaker threshold 3 / cooldown 30min，core/pm_engine/infra_breaker.py:110-138）。断点在归因传递：runner 在异常上挂 exc.api_error_status（runner.py:6046-6049，evo-add-code-review-ratelimit-resume 1.1 落地），但 run_spec_review 的 catch-all（runner.py:1447-1457，:1455 error=str(e)）丢弃之；AgentRunResult（result_gate.py:128-150）无对应字段；stderr 经 _denoise_stderr（runner.py:6084）后只剩 Exit code: 1，文本分类恒 False。评审车道另无并发上限（queue.py:73-78 不占实现槽位、:147 _SLOT_EXEMPT_LANE_TYPES 豁免），批量晋升即并发风暴。

## Goals / Non-Goals

- Goals：429/连接类归因可达失败分类层；评审并发削峰；质量失败重派有节奏；冻结前缀不压制自动恢复。
- Non-Goals：不改 3 次评审预算、熔断参数与回写门 fail-closed；不改兄弟车道；不做跨车道全局限流。

## Decisions

### D1：桥接而非重建（P0）
AgentRunResult 增加 api_error_status / conn_error 字段（result_gate.py:128-150）；run_spec_review catch-all 回填（先例：runner.py:6039-6063 的 exc 挂载与 code_fix 的 conn_error 单源判定 _ratelimit_terminal_hit runner.py:3696+ 三源判定可参照）；_handle_review_failure 的分类入口（spec_review.py:1144）先读结构化字段（429 → infra；conn_error → infra）再回退现有文本词表。命中后自然流入既有 infra 分支与熔断，零新增车道结构。仅归因桥接一项即可使本轮 4 个冻结全部不发生。

### D2：在飞上限套现成范式（P0）
评审上限插入点选 queue.py:389 _review_entry_ready（候选可派发判定），新增 _REVIEW_INFLIGHT_CAP（建议 2-3，config 可配），命中保留条目不 pop（:558 已有「在飞即跳过候选、条目保留」先例；范式同 _PARALLEL_PLAN_INFLIGHT_CAP queue.py:151/:157-159）。不在 engine.py:569-577 晋升处打延迟定时器——定时器受 daemon 重启影响，队列保留天然幂等。

### D3：content 短退避用判重 Timer（P1）
content 分支 _enqueue（spec_review.py:1307）前按 dispatch/backoff.py _schedule_recovery_timer（:241）范式加一档短延迟（秒级即可——本轮实测失败→重派仅 0.05s）；判重集合防重复定时器。infra 分支一律不动，其节奏由熔断负责。

### D4：冻结文案按根因区分的三条红线（P1）
评审自动冻结换用新增的评审专用前缀常量（如「评审供给冻结：」/「评审质量冻结：」），三处评审冻结调用点（spec_review.py:305 尝试上限派发闸门、:726 spec-review-rejected、:1317 尝试上限失败收口）按根因取用。三条红线：① 必须内嵌「原状态 reviewing」子串（state_machine.py:148 parse_orig_status 解冻还原依赖）并保留 spec-review-incomplete 等既有标记子串；② 不得命中 admin_monitor.py:949 _INTENTIONAL_PAUSE_MARKERS 三短语，也不得以 "frozen:" 开头（:972-974 豁免判定的两条文本形态）；③ 仍走 freeze_for_human（state_machine.py:1586）的冻结+告警成对契约。MUST NOT 修改 FREEZE_ERROR_PREFIX 常量值（state_machine.py:64）——freeze_spec 人工冻结路径（:1553）与 parse_orig_status 文档契约（:151）依赖「用户指令冻结」前缀的有意豁免语义，动了即人工冻结豁免失效。机制定位：infra 分类不冻结不递增 attempts，供给瞬态的自动恢复载体是既有熔断冷却；freeze_for_human 置 frozen=True 后 intentionally-paused 豁免（admin_monitor.py:972 首要判据 frozen 字段）必然命中，属「冻结转人工」预期语义——本决策的收益是冻结文案归因准确（自动冻结不得自称用户指令），MUST NOT 以「逃过豁免」为目标。判定输入用 D1 的结构化归因，不做二次文本嗅探。

## Risks / Trade-offs

- AgentRunResult 加字段：兼容性低风险（新增可选字段，既有构造不传即缺省）。
- 在飞上限延长评审尾延迟：批量窗口整体吞吐换取稳定性，上限可配可调。
- 短退避的 Timer 跨重启丢失：退避属节奏优化非正确性依赖，丢失即退回现状立即重派，可接受。

## Migration Plan

单 commit 按 P0（归因桥接 + 在飞上限）→ P1（短退避 + 前缀区分）顺序落地 + 测试；重启 daemon 后生效，无数据迁移。

## Open Questions

- 在飞上限缺省值（2 还是 3）留实现者按网关实际承载定，SPEC 只约束可配。