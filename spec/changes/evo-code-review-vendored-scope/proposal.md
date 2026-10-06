## Why

vendored 第三方示例 whirehair.py（thirdparty/libcimbar/…，public domain、自带上游同步注释）10-02 至 10-07 连续 5 轮 scheduled code-review 被全价出题共 17 个 item，其中两轮 fix batch 实测 $2.3762/17 轮与 $2.0336/13 轮（评审本体另 $1.04/$1.59，两窗口合计约 $7.04），最后两轮以「fenix-ignore 标注保持上游同步」结案。核查证实根因是出题面路径维度缺失：core/code_review.py 的 _EXCLUDED_TOP_DIRS/_EXCLUDED_DIRS（:773-795）排除表不含 thirdparty/vendor，full 档 collect_manifest（:856-922）全仓收集把 vendored 文件每轮必列（该文件是 thirdparty 下唯一 .py，恰好构成长期敞口）；评审提示词 agents/code-review.md:20 更明示「其中的路径是产品代码」，:56-58 的 fenix-ignore 复核规则只挡同位重报——第五轮评审 LLM 明知 vendored 仍按纪律上报，报了就烧一轮 fix batch。

## What Changes

1. 出题面排除 vendored 目录：_EXCLUDED_TOP_DIRS/_EXCLUDED_DIRS 排除表加 thirdparty、third_party、vendor（目录段精确匹配；external 歧义大不收）；full/window 两档与 admin_monitor 侧共用消费点自动生效。
2. 评审提示词如实化：agents/code-review.md「其中的路径是产品代码」改为如实描述（已排除测试/生成物/vendored 第三方目录），并把 :56-58 fenix-ignore 复核规则补强为「漏出排除表但带上游同步标注的文件不上报缺陷条目（只记录不出账）」的第二道防线——评审侧 LLM 只能控制上报与否，「出题」属框架侧行为，提示词措辞以 tasks 1.2 为准。

## Out of Scope

- 不做 vendored 路径可配置化（沿 tests/ 排除的硬编码表先例，无配置面）。
- 不做「仅含标注改动文件不进下一轮 diff 面」过滤（核查证实 full 档入选与改动无关，该过滤无必要；window 档本就按变更窗口收集）。
- 不处理已积累的 ignored 台账条目与上游同步窗口流程。
- 不改 not_worth_fixing/upsert_findings 的指纹抑制语义。