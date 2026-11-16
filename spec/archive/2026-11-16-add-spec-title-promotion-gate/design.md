# Design: add-spec-title-promotion-gate

## Context

中文标题生成纪律现状：fenix-new SKILL.md（§2/§3.1.4/§5）与 evolution 契约（`title_cn` + `_valid_title_cn` + `spec_yaml_text`）均已落地；漏洞在提示词级纪律的**会话快照盲区**（实证 add-spec-subtitle-and-row-click 漏写，2026-11-06）。`.spec.yaml` 全仓写入方穷举 = spec_gen 脚手架（无 title 行，由 skill 步骤补）/ evolution（已带）/ code_review（fix-cr-*，非目标）——写入面封闭，晋升门是最后一道可靠网。

## Goals

1. drafted→ready 晋升门机械拦截缺 title 的 SPEC（fix-cr-* 豁免），违规带处方。
2. 补写一行即自愈，无新增人工介入面。

## Decisions

- **D1 挂点**：`core/pm_engine/promotion.py` 既有 lint 链（`_lint` 族，与 Deliverables 声明 lint / tasks.md 可解析性检查同链同形态）追加一项 `_lint_title`——晋升违规走既有 `drafted + error` 形态与 30 分钟周期重试，零新机制。
- **D2 判定**：活跃 `.spec.yaml` yaml.safe_load 后 `title` 为非空 str 即通过；文件缺失 / 解析失败 / 值空白 → 违规（fix-cr-* 前缀豁免先判）。不做长度校验（D3）。
- **D3 长度不做运行时校验**：5-25 字是生成纪律，读侧契约（`read_spec_title` 全容错）已钉死；硬门只管「存在性」——把形态校验搬进门禁会把展示字段升级成强契约，超出其职责且增加楔死面（门禁平铺事故教训）。
- **D4 豁免口径**：`fix-cr-` 前缀（精确字符串前缀，非正则），对齐 add-spec-chinese-title proposal 非目标声明；不豁免 `fix-*` 泛前缀（手工 fix-* SPEC 与其他通道同等必填）。
- **D5 违规消息处方化**：消息内嵌最小写入示例与规范名（对齐「违规消息即处方」repo 惯例），立项方或交互会话可零上下文补写。

## Risks

- **存量误拦**：存量已全量回填（add-spec-chinese-title 交付 + 两次漏网补填），晋升门只对新晋升生效——零误拦面。实现窗口期新建的 SPEC 若漏 title 会被拦，属预期行为（打回即补）。
- **归档路径无涉**：晋升仅发生在活跃侧，不触碰归档回退语义。
