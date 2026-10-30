# 主树 untracked 散件滞留分级升级与自动认领

<!-- knowledge: capability=stray-untracked-escalation rev=1
     sources=spec/archive/2026-10-30-evo-stray-untracked-escalation -->

主树 untracked 散件（流水线外未跟踪文件）滞留超限时由周期盘点升档为 major 升级信号并自动唤起 Administrator 认领处置——untracked 形态唯一的自动处置出口，与 tracked 散件盘点（[maintree-stray-wip-sweep](maintree-stray-wip-sweep.md)）平行、互不通用。

## 规则

### 三档信号与降噪基线

- untracked 散件盘点共三档信号：`maintree_untracked_stray_stale`（info，超阈值滞留一次性告警）、`maintree_untracked_stray_first_sight`（info，目录型产物集合首现提示，附 gitignore 草案行供预防性 ignore）、`maintree_untracked_stray_escalated`（major，滞留超限升级）。
- 两档 info 信号维持「只告警不处置」：一次性留痕（同指纹/同目录不重复，集合内容增长不重提示），不收录自动唤起注册表、不唤起 Administrator（见 [ADR-295](../../adr/ADR-295-info-inventory-signal-one-shot-escalation-tier-second-signal.md)）；首现提示不启动升级时钟，目录消失复位后再现视为新首现。
- info 滞留告警有既有条目数降噪门：`admin.maintree_untracked_stray_threshold`（缺省 5 entry），低于门槛只建档计时、零 info 零升级告警；该门阈值与一次性语义不受升级能力影响。
- 盘点采集滞留集合条目体积（字节），随告警 evidence 与注册表条目同源暴露；`.fenix/` negation 放行项与已 ignore 路径不计入盘点口径。

### 第二档升级触发

- 升级信号 `maintree_untracked_stray_escalated`（major）触发条件为或语义：滞留时长 ≥ 24 小时，或滞留集合体积 ≥ `admin.maintree_untracked_stray_size_threshold_bytes`（缺省 524288000 字节 = 500MB；解析失败/NaN/±inf/小于 1 一律回退缺省）。
- 体积判定独立于滞留时长：每轮对已告警在册的滞留集合计算体积，MUST NOT 以「elapsed 达标后才计算体积」实现——否则体积超限集合被额外门控进 24 小时内，违背或语义。
- 同一滞留集合只升级一次：注册表双档 escalated 标记 + 升级信号同指纹一次性双兜底；指纹未消失不再重复发出。
- 升级不重置 info 档语义：两档 info 信号保持一次性不重复告警。

### 自动唤起接线（四处登记）

- 新信号类型接入自动唤起须四处同步登记，漏登任一处则记录落 store 后无人摄取、唤起静默落空（每轮巡检重复丢弃）：
  - SIGNAL_SEVERITY：登记 severity（本信号 major）；
  - SIGNAL_RECOMMENDATION：登记处置指引文案——告警写入方与唤起记录 recommended_action 同查此表，漏登则告警无指引；
  - STORED_SIGNAL_TYPES：收录（未收录则记录落 store 后无人摄取）；
  - spec-less 伴生表 SPEC_LESS_STORED_SIGNAL_TYPES：记录固定无 spec 的类型在此登记（须为 STORED_SIGNAL_TYPES 子集），摄取循环据此从 evidence「项目名=」段解析还原 spec。
- 升级信号为项目级盘点、记录无 spec，evidence 以「项目名=」开头供解析；摄取唤起成功后源记录 mark_escalated，二次摄取不重复唤起。

### untracked 认领执行器

- 三种裁决选项（dashboard 裁决清单登记，均 spec_scoped=False 全局信号可执行，执行后处置记录落盘）：
  - `archive_untracked_stray` 显式归档：移入登记目录 `.fenix/stray-archive/<UTC时间戳>/`（保留相对路径结构），登记目录追加 ignore 并独立提交；
  - `ignore_untracked_stray` 追加 .gitignore（既有条目去重不重复追加，文件保留原位）；
  - `delete_untracked_stray` 删除清单内目标文件（清单外无关文件不动）。
- 执行器 signal_type 绑定白名单（UNTRACKED_CLAIM_SIGNAL_TYPES）仅含 `maintree_untracked_stray_escalated`；非白名单信号（含 tracked 桶 `maintree_stray_wip_stale` 与两档 info 信号）在任何 git 读/写之前 fail-closed 拒绝、零 git 写。
- evidence 清单段解析与 tracked 桶执行器共用同一清单解析单源（兼容 info 前身信号格式仅为解析器复用，info 信号不因此放行为执行目标）；「文件清单(N):」段解析对含空格/中文路径稳健。
- 认领执行器独立实现，不复用 tracked 桶 untrack 执行器（git rm --cached 对 untracked 路径无语义、守卫语义不同），untrack 执行器及其守卫保持不动；执行形态遵循「独立执行器 + 复用守卫原语 + 不扩既有门」（见 [ADR-287](../../adr/ADR-287-stray-untrack-executor-independent-no-gate-widening.md)）。

### 能力边界

- 本能力只覆盖 untracked 形态；tracked 桶信号 `maintree_stray_wip_stale` 的触发、处置与 untrack 执行器语义独立演进、不受本能力影响，两桶执行器互不通用。
- admin_alerts 存储保持扁平记录列表，不为升级能力改存储结构。
- 自动唤起放大误报面由三重兜底约束：info 一次性、升级信号同指纹一次性、注册表双档标记。

## 关键行为

- 单轮升级判定：untracked 盘点（entry 降噪门）→ 在册滞留集合体积计算 + 滞留计时 → 或条件命中且未升级过 → 发 `maintree_untracked_stray_escalated`（major，evidence 含文件清单/体积/滞留起点，以「项目名=」开头）→ 注册表记 escalated 标记。
- 认领处置链：升级信号落盘 → 摄取循环按「项目名=」解析 spec → mark_escalated + 唤起 Administrator（recommended_action 非空）→ admin 从裁决清单三选一 → 执行器按清单执行归档/ignore/删除并落盘处置记录。

## 溯源

- 2026-10-30 evo-stray-untracked-escalation（spec/archive/2026-10-30-evo-stray-untracked-escalation） — 新建本页：untracked 散件第二档升级信号（24h 滞留或 500MB 体积阈值、体积路径独立于滞留时长、只升级一次）、自动唤起四处登记接线、untracked 认领执行器三裁决（tracked 信号 fail-closed 拒绝零 git 写）；修订「info 信号一律不收录自动唤起」裁定的适用边界（info 维持不收录、升级信号除外，见 ADR-295）。
