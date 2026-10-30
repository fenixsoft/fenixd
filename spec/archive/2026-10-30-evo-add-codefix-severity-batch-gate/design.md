# design.md

## 上下文

- 被分析项目 potplayer-base 的每日 scheduled 全量评审近 4 轮产出 25 条纯 minor/info 发现并逐日触发完整修复流水线（13 fix + 4 merge），自我供料循环实锤（bin/run_full_suite.py 信号路径连续 4 轮被审被修）。
- 框架现状：/root/fenixd/core/config.py get_code_review_config（:2125）/get_code_review_fix_config（:2216）无严重度键；/root/fenixd/core/code_review.py generate_fix_spec（:1375-1447）仅按 status==open 过滤；/root/fenixd/core/code_fix.py _select_batch_order_key（:1917）按 first_seen_at 排序、checkpoint（:3800）选批，指纹重开在 :2528，链收敛与 chain_skipped 在批收尾对账。
- 范围收缩半个建议已免费：/root/fenixd/core/admin_monitor.py:1591-1629 已实现 scope=window 与空窗跳过，用户级 /root/.fenix/config.yaml:140 显式 scope: full 才走全量。

## 方案

### 1. 配置层（core/config.py）

get_code_review_fix_config 增加两键：
- min_immediate_severity：severity 词表内取值，缺省 major；非法值回退缺省并复用既有配置告警通道。
- minor_batch_cadence：天数（缺省 7）；非法/非正值回退缺省。

沿既有键的校验与回退范式（同 targeted_regression 的 fail-open 风格），不新增异常路径。

### 2. 选批层（core/code_fix.py）

在 checkpoint 选批处（_select_batch_order_key 消费侧）加 severity 过滤：
- severity >= 门限：保持既有当日批序（first_seen_at 排序不变）。
- severity < 门限：跳过并置挂起标记（字段名用 severity_deferred / severity_deferred_since，与既有 WIP-defer 延迟合回台账 fix-deferred.json 的 _deferred_item_ids/first_deferred_at 显式区分——两机制不共载体、不共放行判据）；当 now - 首个 severity_deferred_since >= minor_batch_cadence 天时放行整组。
- regression- 前缀条目（回归来源，severity 为 high/medium/low 值域）豁免门限，保持既有当日处置；「未知档位按低于门限」仅适用于 code-review 来源。
- deferred 条目在链收敛统计、chain_skipped 对账与 is_chain_last_batch 排除口径中按「挂起」计，不计为 skipped/lost（is_chain_last_batch 既有 exclude 集已含 WIP-defer 的 _deferred_item_ids，须扩入 severity 挂起集，与 checkpoint 选批门限同口径）；同指纹重复发现由台账 upsert_findings 既有合并分支免费满足（刷新 last_seen_at 而非新开；reopen_regression_items 仅作用 regression- 前缀条目、与 deferred 主体无关），不新增合并代码；重复发现把 severity 刷到达门限档位时按当日批处置并清除挂起标记。
- 过滤关闭路径：门限缺省 major 且词表含 info/minor/major，min_immediate_severity 配成最低档时行为与现状完全一致（空窗零差异），保证可灰度回退。

### 3. 候选层（core/code_review.py）

generate_fix_spec 的候选筛选（:1422-1428 status==open 之上）应用同一 severity 谓词，使 Dashboard 手工触发与 scheduled 触发走同门；谓词实现放单一函数供两模块导入，避免规则漂移。

### 4. 权衡

- 不引入新执行通道，只改选批单点与候选谓词——与 targeted_regression「优化非门槛」的既有风格同构。
- 不做范围收缩的代码改动：scope=window 与空窗跳过已存在，属配置回拨（运维步骤入任务书）。
- 增量范围无法完全消除自供料（fix 合并落次日窗口），故本设计以分级门限为主杠杆，范围回拨为辅。

### 5. 风险

- deferred 与指纹重开/链收敛的交互是最大风险点：测试须覆盖 deferred 期间重复发现、deferred 跨周批晋级、门限回退三条路径。
- severity 词表实测为四档 critical|major|minor|info（core/code_review.py:427-431，normalize_severity 把 high/medium→major、low→minor 归一）；门限比较按档位序 info<minor<major<critical，min_immediate_severity 配成最低档 info 时与现状零差异。
- 词表硬编码 severity 的评审来源若未来出现新档位，须显式映射后才能进入选批（code-review 来源未知档位按低于门限处理并告警，fail-open 挂起而非误修；regression- 来源条目豁免门限，不受该规则影响）。
