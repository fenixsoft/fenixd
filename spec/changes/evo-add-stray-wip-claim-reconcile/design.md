# 设计：散件指纹入库自动核销升级告警

## Context

maintree_stray_wip_stale 的处置协议是「零触碰+逐度升级转人工」，但消费端只有人工：escalated=true 的 signal 条目被 core/admin_monitor.py:4233-4240 摄取循环豁免于一切自动处置（`if rec.get("escalated"): continue  # 已唤起过，跳过`；唯一例外 provider_ref_invalid 经 admin_store.py auto_resolve_by_type_fingerprint 白名单核销，core/config.py:200 登记）。指纹归一、周期盘点、registry 复位（core/worktree_manager/stray_wip.py 盘点编排 `_sweep_locked`）齐备，唯独没有「指纹文件集全部入库 = 人工认领」的探测。实证（spec-review 就地更正）：在案信号条目 34ae21ea0362（33 文件，2026-11-11 起 escalated=true 悬置）指纹文件集已被基线后多波主树提交覆盖（最近 b73716af4 2026-11-16）但余 2 文件尚脏、至今 handled=false；原引 dsh-plugins 提交 47fefd9 属独立仓库、不在本族盘点面内。该族跨日烧 3 个 admin run ≈$4.25。

## Goals / Non-Goals

- **Goals**：升级条目结构化携带指纹清单；盘点轮机械探测「集合全部入库」并自动核销回填 commit；存量旧形态条目回提取参与；未命中保守保留。
- **Non-Goals**：不改动处置侧协议（零触碰+升级节奏照旧——核销是消费端增量，不减少升级发生）；不扩展到其它告警族（白名单单族起步，通用「条件消失核销」属既有另一条目）；不做 worktree 车道自动建立（那是人工裁决的另一半，只转话术提示）。

## Decisions

**D1 认领判据=指纹集合全部入库，一问即答。** 对条目指纹文件集在 sweeper project_root 内以 `git -C` 跑 `git log -- <files>`（对齐 stray_wip.py:549 既有调用纪律；不跨仓），基线时刻之后存在覆盖全部文件的提交（≥1 个，覆盖提交数不限）且 working tree 该集合 clean 即认领；任一文件未被基线后提交覆盖或集合内仍有脏文件一律不核销——防半处置假闭环由「全覆盖+集合 clean」承担，与提交数无关（spec-review 修正：原「命中单 commit」与 spec.md「全部被新提交覆盖」不一致，且在案 33 文件条目由多波提交覆盖、单提交判据会使其永不核销）。**插桩位置红线**：探测 MUST 挂在盘点轮空集早退之前（对齐 evo-whitelist-tracked-patrol 1.1「早退不得吞掉本流判定」先例——`_sweep_locked` docstring 明示 tracked 零改动时直接返回 clean；人工提交完指纹集后恰是 tracked 空集形态，插桩在后则核销目标时点永不执行）。

**D2 白名单单族+结构化清单优先。** 探测只挂 maintree_stray_wip_stale 的 kind=SIGNAL 记录（照 provider_ref_invalid 单族先例；disposition 留痕无文件集且不属 SIGNAL 唤起面，不参与）；新条目写结构化文件集字段，存量条目从 evidence「文件清单(N):」段回提取（复用既有段级解析单源口径——`parse_stray_wip_manifest` 与 `_prior_stray_rounds` 同款，禁新写路径正则双处解析），失败保守跳过——不核销的代价是继续悬置（现状），误核销的代价是吞掉真问题，保守侧正确。

**D3 核销落 resolve_note 带转向话术。** handled_by="auto-resolve-claim"，note 含认领 commit SHA（多波覆盖时回填最近覆盖提交 SHA）+「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」——消费端核销与人工后续裁决（建车道 or 认可直改）分离，与「不信任 agent 自述、只认机械证据」的告警生命周期宪章一致（入库 commit 是机械证据）。**核销署名与复发台账互斥**：复发计数检索（stray_wip.py `_prior_stray_rounds`）MUST 跳过 handled_by="auto-resolve-claim" 的记录——自动核销不是人工处置轮，计入会使下次同文件告警误带「已 N 度处置」根治口径（untrack_stray_wip 对源码清单属仓库损伤）。

## Risks

- 人工以非提交形态处置（stash/手动删除）则探测不命中：条目继续悬置走原升级路径，行为等于现状，无回归。
- 回提取正则漏配：保守跳过，仅存量条目受影响且新条目已有结构化字段兜底。