# ADR-289：出题面路径排除收收集层单表硬排除，不配置化不以评审侧预标替代

date: 2026-10-28
status: accepted

## Context

vendored 第三方受控文件（自带上游同步注释、缺陷由上游同步流程承接）连续多轮 scheduled code-review 被全价出题，逐条以 fenix-ignore「保持上游同步」标注结案仍烧 fix batch（实证单文件 5 轮 17 item、两轮 fix batch $2.38/$2.03）。根因在出题面收集层没有 vendored 维度：排除表只有测试/生成物等目录，vendored 文件每轮必入 manifest；评审提示词还宣称「manifest 路径是产品代码」，评审 LLM 明知 vendored 仍按纪律上报。候选路径有三：收集层硬排除、评审后按 vendored 属性自动预标 not_worth_fixing、提示词侧劝阻上报。

## Decision

vendored 路径排除收在收集层：目录名单（thirdparty/third_party/vendor，目录段精确匹配；external 歧义大不收）维护进出题面排除单表（与 tests/ 等既有排除同表，其余判据由单表派生、禁重复手写），full/window 两档与 admin 侧共用消费点自动生效，零 token 成本。不采用评审后自动预标（预标仍须每轮先付评审成本才能发现 vendored 属性）；提示词只承担如实描述收集范围与 fenix-ignore 上游同步标注的第二道防线（漏出排除表的标注文件不出缺陷条目），不承担排除职责。排除表沿 tests/ 排除先例硬编码，不做路径配置面。

## Consequences

vendored 缺陷面永久退出周期全价重审，风险由上游同步流程与文件内标注承接，个别 vendored 文件确需审查时在上游同步窗口人工触发专项评审；非标准 vendored 布局可能绕过名单，由第二道防线兜底（标注文件不出题，零漏审）。排除表是清单可扩展的硬编码表：后续任何新的出题面路径排除诉求一律走该单表追加并沿用目录段精确匹配口径；要引入配置面、把排除挪到评审侧或依赖预标机制，须显式 supersede 本裁定。
