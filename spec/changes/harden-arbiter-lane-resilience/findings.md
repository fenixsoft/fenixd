# Findings — 调查归因（任务 1.1）

## 事故现场引用（2026-11-09，cloud_phone 项目）

- `.fenix/arbiter_ledger.jsonl` 本地 09:01–09:08（UTC 01:01–01:08）四签名
  `failed→dead-man→recurrence-escalation→chain-escalated` 四连，
  `arbiter_rulings=0`；failure_reason 两层：
  - `dsh: skipping profile bundle "fenix-dsh-bundle": Plugin ...@0.1.0 incompatible with dsh 0.2.2-rc.1`
  - `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"`
- fenixd.log：`latency: run arbiter-...: 0 rounds（无 API 往返样本）`，单 run
  0.002s（1800s 墙钟预算几乎全额剩余）——0 rounds + 环境指纹双命中。
- 前日首败（2026-11-08T08:07Z）：`[Errno 2] No such file or directory: 'claude'`——同一车道同类基础设施故障。
- 修复对照：config.yaml 显式模型链落地后 17:29 车道正常产裁决包——车道能力无问题，问题全在环境面与环境恢复后的资格恢复缺失。

## 连败→dead-man 链（core/pm_engine/arbiter.py）

- `_on_run_failed`（:1276-1361）：:1290-1294 连败计数（`_failure_counts`）+
  `_active.discard`；:1301-1303 `count >= max_consecutive_failures` **或**
  `budget.tokens_exhausted/wallclock_exhausted` → dead-man；:1305
  `_deadmanned.add(sig)`；:1315-1326 台账 kind=dead-man；:1327-1339
  `_upgrade_alert`（人工升级）；else :1346-1361 kind=failed 留待重试。
- **budget 耗尽与连败共用同一分支**——分级实现 MUST 先判 infra/预算，
  预算耗尽恒判 judgment（真实消耗，design §能力一）。
- dead-man 无复位确认：`_deadmanned` 内存集合（:246）+ 持久读
  `_ledger_sigs(kinds={"dead-man"})`（:388 submit_trigger 配额判定、:671
  回扫排除）——台账只读不写、无解除 API。

## 台账读侧消费者清单（infra-failed 新 kind 兼容性）

- `load_arbiter_ledger`（:172-199）：fail-open 全量读，`\n` 硬分割
  （append-only 纪律 :180-199 注释）；新 kind 是追加行，零结构破坏。
- `_ledger_sigs`（:626-642）：按传入 kinds 过滤；现行全部消费点
  kinds={"dead-man"}（:388、:671）——infra-failed 行对二者透明。
- 回扫排除 `_backlog_candidates`（:644-671）：只按 dead-man 永久例外 +
  复现配额耗尽排除（「任意 kind 即已调查过」判定已随配额制反转删除，
  :664-670 注释可证）——infra-failed 行不阻塞回扫重试。
- escalation_chain 侧台账消费者：`_deadmanned`（:1791-1804）按
  `DEADMAN_LEDGER_KINDS = frozenset({"dead-man"})`（:84）过滤——新 kind
  不命中，dead-man 判定不变；链事件按 run 联查（:1424-1432）只认
  chain-closed/chain-handoff kind——零交集。
- `_write_ledger`（:1365+）五段补全逻辑对新 kind 天然生效（
  `ledger_entry_complete` 验收口径满足）。
- **配额零副作用**：`count_arbiter_ruling` 仅在 `_on_escalate`
  （arbiter.py:1235-1239）调用；infra 失败不进 escalate 出口 → 拍板配额
  不被 infra 故障燃烧。

## 0 rounds 判定口径

- `run_arbiter` 信封（maintenance_runs.py:712-910）现无 rounds 键；
  内部 `turns` 已有（:800 初始化、:812-821 `_run_agent` 返回 5 元组第 2
  位，runner.py:8209 `return output, turns, ...`）——信封补
  `"rounds": turns` 透传即可。
- latency.py:246-247 `stats.get("rounds", 0) <= 0` 是「无 API 往返样本」
  判定口径（0 rounds 文案 :247 即由它产生）；分类函数按信封
  `rounds <= 0` 判定，**不从文案反解**（design 约束）。
- 注意：`_run_agent` 抛异常路径 turns 无值——信封兜底 rounds=0，但
  异常 error 已带环境指纹（shutdown-interrupted/signal-kill 标签），
  双判据互补。

## 环境指纹识别面

- `MISSING_CREDENTIAL`：dsh 运行期凭据缺失错误码（dsh_adapter.py:743、
  :946-950 凭据桥接缺失即秒挂、:973 分类不入熔断）。
- `No such file or directory`：CLI 二进制缺失（Errno 2）；既有
  `precheck_harness_executable`（harness/__init__.py:143-153）+
  `[harness-cli-unavailable]` 标记（protocol.py:171）已覆盖探测面。
- `skipping profile bundle`：dsh bundle 不兼容跳过——`DshAdapter.
  check_health`（dsh_adapter.py:1159-1189，`--version` + 版本白名单 +
  Bundle 挂载探测）前置探测即可在派发前命中同类故障。
- exit=1 且 rounds=0：0 rounds 判据子集（design 评审注），冗余保留仅作
  归因可读性。

## 链消费面（escalation_chain.py）

- `_run_arbiter_phase`（:1563-1594）：循环 `outcome != "failed"` 即
  break——infra 终态字返回后无循环重派风险；:1587-1594 非 resolved
  一律回填 endpoint 并上升（:905-910 `_endpoint_escalate`）——MUST
  在调用方（:902-910）新增 infra-failed 消费分支：不上升、不重派、
  留痕等回喂。
- deferred 让行范式（:821-847）是**互斥让行专用形态**（知识页
  escalation-chain：deferred 收窄为互斥让行专用，空 yield_to legacy
  分支退役中）——infra 停机无被让行对象，MUST NOT 走
  `defer_in_flight`；留痕用 `_write_chain_event`（:1807-1848）落
  chain 事件（台账追加行，时间轴/处置链视图可查），信号闭环靠既有
  触发面复报/回扫候选重扫自然回喂。

## 拦截点位与告警面

- `submit_trigger`（:346-372）：拦截置于 `enabled`/黑名单 `excluded`
  判定**之后**（关闭态零侵扰纪律：enabled=false 不派发不拦截不产生
  台账——知识页 arbiter-lane）、dedup/`_recurrence_inflight` 消费
  **之前**；命中返回既有终态字 `deduped`（零新契约）。
- `process_chain_handoff`（:938-963）：拦截置于 `_consume_pending_bind`
  之前；命中返回 `infra-failed`（链消费分支承接）。
- 告警单发/自动关闭：`AdminStore.append_if_absent`（dedup_key 判据，
  fenixd.py:945-967 harness 自检同款）+ `auto_resolve`（按记录 id 收口，
  handled_by=auto-resolve，admin_store.py:1085-1102）——恢复 healthy
  时按 signal_type+dedup_key 查在案未处理条目 id 后收口。

## 配置面

- `get_arbiter_config`（config.py:2850-2884）现四键白名单 dict——
  不加白名单旋钮恒缺省（design §配置面）；扩两键：
  `max_consecutive_infra_failures`（缺省 = 既有连败上限同值 2）、
  `preflight_ttl`（缺省 300）。
- 车道配置读取单源：`ArbiterLane.config()`（arbiter.py:267-281）经
  ConfigLoader——新键经同一入口消费，不旁路直读。

## 周期节拍挂靠点

- fenixd.py 主循环（:1441 `while self.running` 1s tick）：既有时间门
  范式（config 30s :1528、recovery watch 60s :1537）——周期重探挂 60s
  时间门，禁内存定时器纪律满足。
