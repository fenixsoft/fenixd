# 提案：散件指纹入库自动核销升级告警

## Why

maintree_stray_wip_stale 的升级条款（第 4 度起零触碰+升级转人工）没有任何「人工已回应」的消费端——告警文本自述「等待人工提交或 stash 处置」，但当人工真的以提交精确处置了全部指纹文件（实证：dsh-plugins 11-14 18:39 提交 47fefd9 --stat 含且仅含指纹 5 文件+同特征 untracked 兄弟），框架零感知：4 条告警/处置条目自创建起悬置 23.5 小时+ 全部 handled=false，escalate=true 条目被 admin_monitor 豁免于一切自动处置，下次同文件滞留将按第 5 度条款继续零触碰+升级，悬置逐度累加成永久挂账。该族跨日已烧 3 个 admin run（≈$4.25）空转对账。指纹文件集全部进入 main 新提交是机械可判的认领信号，探测缺位纯属消费端空白。

## What Changes

- **升级条目挂指纹清单（core/admin_monitor.py）**：maintree_stray_wip_stale 升级条目生成处把指纹文件集（路径列表）写进条目结构化字段，核销探测可机械消费，不解析自然语言 evidence。
- **认领探测与自动核销（core/worktree_manager/stray_wip.py + core/admin_store.py）**：周期盘点对每个未核销的该族升级条目检测指纹文件集是否已全部被 main 基线后新提交覆盖（git log -- <files> 一问即答）；命中即核销（handled=True、handled_by="auto-resolve-claim"），resolve_note 回填认领 commit SHA 与转向话术「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」；任一文件未入库则逐位保留原状（升级节奏不变）。
- **存量回填（core/admin_store.py）**：无指纹清单字段的旧形态悬置条目按 evidence 文本回提取文件集参与同一探测，回提取失败保守跳过（照 auto_resolve_by_type_fingerprint 的白名单+保守缺省形态）。

## Capabilities

- `specs/stray-wip-claim-reconcile/spec.md` — ADDED：散件指纹入库自动核销升级告警

## Impact

- **受影响模块**：`core/admin_monitor.py`（升级条目生成处补结构化指纹清单）；`core/worktree_manager/stray_wip.py`（周期盘点挂认领探测）；`core/admin_store.py`（核销写回+存量回填）；新增专项测试+既有 sweep 测试回归锚。
- **兼容性**：认领探测只对 maintree_stray_wip_stale 族生效（白名单形态，照 provider_ref_invalid 先例）；未命中/回提取失败/非 git 仓库全部保守跳过零行为变化；处置侧 sweep 行为（零触碰+升级节奏、指纹归一 :756、registry 复位 :871）零改动。
- **无 UI、无数据迁移、无配置键**；直接效果：在案 4 条悬置条目随下一轮盘点自动核销，第 5 度升级不再空转。