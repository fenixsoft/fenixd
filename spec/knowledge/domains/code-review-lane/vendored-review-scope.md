# 审查出题面 vendored 目录排除
<!-- knowledge: capability=vendored-review-scope rev=1
     sources=spec/archive/2026-10-28-evo-code-review-vendored-scope -->

代码审查出题面（manifest 收集）对 vendored 第三方目录的排除规则与评审提示词如实化约束：受控上游同步的第三方代码不进入周期性全价重审，杜绝「明知 vendored 仍出题→逐条标注结案→烧 fix batch」的循环。

## 规则

- vendored 第三方目录不入出题面：manifest 收集（scope=full 全仓收集与 scope=window 变更面收集两档共用消费点）排除目录段精确匹配 `thirdparty`、`third_party`、`vendor` 的路径，命中路径不进入 manifest files，即不被出题、不付评审与修复成本。
- 目录段精确匹配语义：任意层级下目录段与名单全等才排除；近名目录（如 `vendors`、`vendorkit`）与 `external` 不受排除影响（`external` 歧义大——仓内自有代码也可能叫 external，不入名单）。
- 排除名单维护在收集侧排除单表（`core/code_review.py` 的 `_EXCLUDED_TOP_DIRS`，与 `tests/`、`docs/`、`dist/`、`.fenix/`、`.git/`、`spec/` 同表）；`_EXCLUDED_DIRS` / `_EXCLUDED_PREFIXES` 两套判据由该单表派生（消除漂移面），MUST NOT 在派生表重复手写 vendored 段。
- 两档与 admin 侧自动生效：排除在收集层单点生效，full 档、window 档及 admin_monitor 侧共用消费点经同一排除表自动生效，无需逐处适配。
- 非 vendored 路径的收集行为不变：排除只作用于目录段命中的 vendored 路径，其余源码收集、`max_files` 截断等行为不受影响。
- 排除是收集层硬排除而非评审后处置：不采用「先出题评审、再按 vendored 属性预标 not_worth_fixing」的路径（预标仍须每轮先付评审成本才能发现 vendored 属性）；vendored 目录名是稳定信号，在收集层排除零 token 成本。
- 排除表为硬编码清单（与 `tests/` 等既有排除同表维护），不做路径配置面；出现真实项目差异需求时再议配置化。

## 关键行为

- 评审提示词如实描述收集范围：提示词不得宣称 manifest 路径一律是产品代码，须如实表述收集面已排除测试代码、文档、构建生成物与 vendored 第三方目录（vendored 文件的缺陷由上游同步流程承接，不逐轮审查）。
- fenix-ignore 上游同步标注是第二道防线：排除表可能被非标准 vendored 布局绕过；对漏出排除表、但文件内带 fenix-ignore 标注且理由为保持上游同步的文件，评审复核规则指示不出缺陷条目——只记录该事实、findings 置空、不上报。复用既有 fenix-ignore 忽略标记约定，无新增标注格式。
- vendored 缺陷的承接面：排除后 vendored 内缺陷不在 scheduled 全价审查面出现，风险由上游同步流程与文件内的 fenix-ignore 标注、上游同步注释承接；vendored 内个别文件确需审查时，在上游同步窗口人工触发专项评审，不走 scheduled 全价面。

## 溯源

- 2026-10-28 evo-code-review-vendored-scope（spec/archive/2026-10-28-evo-code-review-vendored-scope） — 新建本页：出题面收集层排除 vendored 三目录（thirdparty/third_party/vendor，目录段精确匹配，单表派生两档自动生效），评审提示词如实描述收集范围，fenix-ignore 上游同步标注文件不出缺陷条目的第二道防线。
