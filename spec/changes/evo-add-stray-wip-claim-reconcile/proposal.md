# 提案：散件指纹入库自动核销升级告警

## Why

maintree_stray_wip_stale 的升级条款（逐度零触碰+升级转人工）没有任何「人工已回应」的消费端——告警文本自述「提交（git add/commit）或 stash 处置」，但当人工真的以提交处置了指纹文件（spec-review 就地更正实证：原引 dsh-plugins 11-14 18:39 提交 47fefd9 属独立仓库、不在本族盘点面内——本族只扫 daemon 主树，sweeper 单实例锚定 project_root，stray_wip.py:549 git -C 调用、pm_engine/engine.py:5611 消费；真实在案形态为信号条目 34ae21ea0362：33 文件清单、2026-11-11 起 escalated=true 悬置，指纹文件集已被基线后多波主树提交覆盖（最近 b73716af4 2026-11-16）但余 2 文件尚脏、至今 handled=false），框架零感知：escalated=true 的 signal 条目被 admin_monitor.py:4239-4240 摄取循环豁免于一切自动处置（「已唤起过，跳过」），同文件再滞留将继续按复发口径零触碰+升级，悬置逐度累加成永久挂账。该族跨日已烧 3 个 admin run（≈$4.25）空转对账。指纹文件集全部进入 main 新提交是机械可判的认领信号，探测缺位纯属消费端空白。

## What Changes

- **升级条目挂指纹清单（core/worktree_manager/stray_wip.py）**：maintree_stray_wip_stale 告警落库记录构造处把指纹文件集（路径列表）写进记录结构化字段，核销探测可机械消费，不解析自然语言 evidence。（spec-review 修正归属：该族记录在 stray_wip 落库、admin_monitor 仅三表登记与 SIGNAL 摄取，admin_monitor.py 无「升级条目生成处」可挂）
- **认领探测与自动核销（core/worktree_manager/stray_wip.py + core/admin_store.py）**：周期盘点对每个未核销的该族升级条目检测指纹文件集是否已全部被 main 基线后新提交覆盖（git log -- <files> 一问即答）；命中即核销（handled=True、handled_by="auto-resolve-claim"），resolve_note 回填认领 commit SHA 与转向话术「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」；任一文件未入库则逐位保留原状（升级节奏不变）。
- **存量回填（core/admin_store.py）**：无指纹清单字段的旧形态悬置条目按 evidence 文本回提取文件集参与同一探测，回提取失败保守跳过（照 auto_resolve_by_type_fingerprint 的白名单+保守缺省形态）。

## Capabilities

- `specs/stray-wip-claim-reconcile/spec.md` — ADDED：散件指纹入库自动核销升级告警

## Impact

- **受影响模块**：`core/worktree_manager/stray_wip.py`（告警落库补结构化指纹清单+周期盘点挂认领探测+复发计数台账跳过自动核销记录）；`core/admin_store.py`（核销写回+存量回填）；新增专项测试+既有 sweep 测试回归锚。
- **兼容性**：认领探测只对 maintree_stray_wip_stale 族 kind=SIGNAL 记录生效（白名单形态，照 provider_ref_invalid 先例）；未命中/回提取失败/非 git 仓库全部保守跳过零行为变化；处置侧 sweep 行为（零触碰+升级节奏、指纹归一、registry 复位）零改动。
- **无 UI、无数据迁移、无配置键**；直接效果：证据可提取的该族 signal 条目在其指纹文件集全部入库且工作区 clean 的下一轮盘点自动核销（在案 34ae 条目余 2 文件入库后即命中）；disposition 留痕记录无文件集且不属 SIGNAL 唤起面，不在探测范围（其闭合走既有链上台账机制）。