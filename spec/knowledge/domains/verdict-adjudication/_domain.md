# 验证裁决与证据
> 最后更新：2026-10-30 23:11 UTC+8

验证裁决与证据：覆盖裁决产物的产生与门检、证据分类与归因可信度、裁决结果与失败语义、查重与重合成、缓存复验、env 类失败的豁免握手与场景修订处置出口，以及裁决在 Dashboard 的可见性。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [verifier-judgment-integrity](verifier-judgment-integrity.md) | verifier 判定完整性 | 2026-10-03 04:59 |
| [verdict-contract-singularity](verdict-contract-singularity.md) | 裁决契约单一性 | 2026-10-03 04:59 |
| [verdict-result-integrity](verdict-result-integrity.md) | 裁决结果完整性（fail-closed 读取） | 2026-10-03 04:59 |
| [verdict-failure-semantics](verdict-failure-semantics.md) | 裁决失败语义 | 2026-10-03 04:59 |
| [verdict-failure-passthrough](verdict-failure-passthrough.md) | 失败结论透传 | 2026-10-03 04:59 |
| [verdict-evidence-taxonomy](verdict-evidence-taxonomy.md) | 裁决证据分类 | 2026-10-03 04:59 |
| [verdict-attribution-evidence-gate](verdict-attribution-evidence-gate.md) | 裁决归因证据门 | 2026-10-03 04:59 |
| [attribution-freshness-governance](attribution-freshness-governance.md) | 归因新鲜度治理 | 2026-10-03 04:59 |
| [screenshot-evidence-labeling](screenshot-evidence-labeling.md) | 截图证据标注 | 2026-10-03 04:59 |
| [verifier-selector-evidence](verifier-selector-evidence.md) | verifier 选择器证据 | 2026-10-03 04:59 |
| [verified-gate-evidence](verified-gate-evidence.md) | verified 门证据持久化 | 2026-10-03 04:59 |
| [verdict-dedup-resynthesis](verdict-dedup-resynthesis.md) | 裁决去重与重合成 | 2026-10-03 04:59 |
| [verdict-cache-reverify](verdict-cache-reverify.md) | 裁决缓存复验 | 2026-10-03 04:59 |
| [verdict-visibility](verdict-visibility.md) | 裁决可见性（Dashboard 呈现） | 2026-10-03 04:59 |
| [judge-artifact-gate](judge-artifact-gate.md) | judge 产物硬门 | 2026-10-03 04:59 |
| [judge-artifact-checkpoint](judge-artifact-checkpoint.md) | judge 产物检查点 | 2026-10-03 04:59 |
| [judge-incremental-attribution](judge-incremental-attribution.md) | judge 增量归因 | 2026-10-03 04:59 |
| [judge-rerun-governance](judge-rerun-governance.md) | judge 重跑治理 | 2026-10-03 04:59 |
| [inconclusive-loop-escalation](inconclusive-loop-escalation.md) | 无结论循环升级 | 2026-10-03 04:59 |
| [verdict-env-exemption-handshake](verdict-env-exemption-handshake.md) | 裁决 env 豁免与 admin 升级链握手（豁免不得自我批准） | 2026-10-15 02:25 |
| [scenario-revision-reverify-exit](scenario-revision-reverify-exit.md) | 场景修订重验出口（env 阻塞的第三出口：白名单内修订场景与夹具后重验） | 2026-10-15 02:25 |
| [verdict-step-failure-evidence-derivation](verdict-step-failure-evidence-derivation.md) | 步骤失败型裁决证据派生（空表形态机械派生缺省失败清单） | 2026-10-06 03:13 |
| [verdict-attribution-dedup](verdict-attribution-dedup.md) | 批量归因查重级联豁免（依赖级联同因组免「≥3 同文即拒」） | 2026-10-09 11:16 |
| [judge-result-freshness-hygiene](judge-result-freshness-hygiene.md) | 裁决结果文件轮间卫生（派发前改名留档 + 陈旧残留重试前清理） | 2026-10-14 01:44 |
| [judge-repair-budget-alignment](judge-repair-budget-alignment.md) | judge 修复预算口径统一（耗尽后无修复纯归因跨重启持久、受理点机械门禁穿透假 verified、硬上限冻结告警附修复预算上下文） | 2026-10-30 23:11 |
| [verify-verdict-run-attribution](verify-verdict-run-attribution.md) | verdict 文件 run 级归属戳与采信判据（派发预写戳、消费三分支、残留禁作本轮输入、丢弃前 report.json 保全） | 2026-10-30 23:11 |
