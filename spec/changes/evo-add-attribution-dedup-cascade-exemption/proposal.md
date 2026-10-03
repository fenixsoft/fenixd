# add-attribution-dedup-cascade-exemption

## 背景

2026-10-03 potplayer-base 的 android-station-port 两轮验证各触发一次批量归因查重拒绝，各多派一次轻量重合成 judge run（合计 $1.3602、墙钟 570 秒）。第二轮被拒 5 场景全部是宿主缺 Gradle/adb 导致的依赖级联 blocked-env（引擎日志 17:29:46/17:35:22 逐条记录依赖跳过链）——引擎对依赖跳过场景合成统一模板文案与空证据（core/verify_engine/engine.py:397-426，dependency_skipped=True），此类场景的正确归因本就逐字相同，而查重门（core/verdict_check.py:1280-1362，「归一化后逐字相同且组内 ≥3」即拒）无任何同因组豁免分支（D3 细分注释 :1104-1115 自认「不设组内豁免分支」，且依赖跳过形态无步骤/断言可细分，逃生通道结构性不可用）。存量定价假设被证伪：2026-09-15-add-verdict-credibility-gate design.md:50 认定同因误伤「重合成即可，不烧预算」，实测每次 $0.44-0.92＋4-5 分钟裁决车道。

## 目标

1. 依赖级联同因组豁免：dependency_skipped 场景单列同因组，不参与「≥3 同文」判拒，仅校验非样板字段。
2. 混合组判拒语义不变：含真实 failed 场景的同文组（模板套用嫌疑）仍照拒，防套用能力不回退。
3. 豁免决策留痕：拒绝 reason 区分「同因级联组豁免」与「模板套用嫌疑」；豁免决策随查重结果结构与验证日志留痕可追溯。

## 非目标

- 不改查重阈值 ≥3 与归一化指纹构成（verdict_check.py:1204-1240）。
- 不改跨轮缓存 schema（缓存不含归因文本，「缓存携带同因组标记」方案无落点，弃用）。
- 不改重合成派发链（core/pm_engine/verification/verdict_evidence.py 的拒绝收口链 _rejection_closure 及重合成派发族）。

## 验收

- 纯依赖级联组（如 5 个 dependency_skipped blocked-env 同文）不再触发拒绝、不再派重合成 run。
- 混合组（3 个真实 failed 同文＋级联场景）仍被拒绝，reason 文案不变。
- 豁免决策随查重结果结构与验证日志留痕可追溯，拒绝决策经既有收口链留痕不变；既有 D3 细分（步骤/断言各异豁免）行为不回退。
