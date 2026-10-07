# 提案：验证证据分级留存（verify-evidence-tiered-retention）

## 背景

potplayer-base 仓库已跟踪验证证据 67 个文件共 690MB、仓库 size-pack 641.42 MiB（复核于 2026-10-08）。膨胀全部发生在项目根 verify-evidence/（按 pack 命名、契约外目录）：框架从不执行 git add 证据，验证证据落位契约（evo-add-verify-evidence-placement-contract）指向的 .fenix/verify-evidence/<spec>/ 本被 .gitignore 的 .fenix/* 规则天然排除——690MB 全部源于 agent 契约外手工提交。两轮实证：10-03 提交 c91213f 一轮入库 8 个互异 Ambient_Loop_000.mp4（裸增量约 657MB，无跨包去重）；10-07 提交 6f1042e 又入库 2×27MB mp4（内容寻址去重后一份），而同目录 sha256 sidecar 与 README 哈希旁证已在场，二进制本体对「逐字节一致」论证无增量价值。

core/verify_contract.py（2362 行）现无任何体积/类型分级逻辑；spec/changes 现存 52 条无一覆盖已跟踪证据分级。

## 目标

1. 验证证据落位契约支持可选的留存分级声明：文本/JSON/哈希/小日志直接入库；超过阈值（缺省 10MB）的二进制不入 git，改以 sha256 sidecar + 复现命令 + 存放路径登记。
2. 落位指引（prompt 注入）携带分级条款，使 agent 在产证据时即按档位处置。

## 非目标

- 存量 690MB 已跟踪二进制的迁移外置：涉及 git 历史改写，须人工评估（可参考用户级 ~/.claude/skills/share-file-via-cos 通道），不在本 SPEC。
- untracked 散件滞留与告警升级：由相邻 spec（散件滞留告警升级）与既有 placement 契约收口。
- 项目侧 .fenix/verify.yaml 的 evidence_dir 接线：属配置采用动作，不属本 SPEC 代码改动。

## 验收口径

- 契约解析对 evidence_retention.max_binary_bytes 三态行为正确（声明生效/非法回退/缺省走 10MB）。
- 落位指引文本在声明与缺省两种形态下均渲染分级条款。