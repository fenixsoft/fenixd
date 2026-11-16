# 设计：散件指纹入库自动核销升级告警

## Context

maintree_stray_wip_stale 的处置协议是「零触碰+逐度升级转人工」，但消费端只有人工：escalate=true 条目被 core/admin_monitor.py:8448-8453 豁免于一切自动处置（唯一例外 provider_ref_invalid 经 admin_store.py:1615-1643 auto_resolve_by_type_fingerprint 白名单核销，config.py:1126 登记）。指纹归一（core/worktree_manager/stray_wip.py:756）、周期盘点（:707/:722）、registry 复位（:871）齐备，唯独没有「指纹文件集全部入库 = 人工认领」的探测。实证：47fefd9 精确处置 5 指纹文件后 4 条条目悬置 23.5h+，该族跨日烧 3 个 admin run ≈$4.25。

## Goals / Non-Goals

- **Goals**：升级条目结构化携带指纹清单；盘点轮机械探测「集合全部入库」并自动核销回填 commit；存量旧形态条目回提取参与；未命中保守保留。
- **Non-Goals**：不改动处置侧协议（零触碰+升级节奏照旧——核销是消费端增量，不减少升级发生）；不扩展到其它告警族（白名单单族起步，通用「条件消失核销」属既有另一条目）；不做 worktree 车道自动建立（那是人工裁决的另一半，只转话术提示）。

## Decisions

**D1 认领判据=指纹集合全部入库，一问即答。** 对条目指纹文件集跑 `git log -- <files>` 于告警基线时刻之后命中单 commit 且 working tree 该集合 clean 即认领；部分入库/仍有脏文件一律不核销——「精确处置」才核销，避免半处置假闭环。

**D2 白名单单族+结构化清单优先。** 探测只挂 maintree_stray_wip_stale（照 provider_ref_invalid 单族先例）；新条目写结构化文件集字段，存量条目从 evidence 文本回提取（路径形态正则），失败保守跳过——不核销的代价是继续悬置（现状），误核销的代价是吞掉真问题，保守侧正确。

**D3 核销落 resolve_note 带转向话术。** handled_by="auto-resolve-claim"，note 含认领 commit SHA +「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」——消费端核销与人工后续裁决（建车道 or 认可直改）分离，与「不信任 agent 自述、只认机械证据」的告警生命周期宪章一致（入库 commit 是机械证据）。

## Risks

- 人工以非提交形态处置（stash/手动删除）则探测不命中：条目继续悬置走原升级路径，行为等于现状，无回归。
- 回提取正则漏配：保守跳过，仅存量条目受影响且新条目已有结构化字段兜底。