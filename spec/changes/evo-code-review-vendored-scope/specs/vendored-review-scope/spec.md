# vendored-review-scope Specification

## Purpose

code-review 出题面不再把 vendored 第三方目录当产品代码全价重审；评审提示词如实描述收集范围，杜绝「明知 vendored 仍出题→逐条标注结案→烧 fix batch」的循环。

## Requirements

### Requirement: vendored 目录出题排除

code-review 出题面收集（full 与 window 两档共用）MUST 排除 vendored 第三方目录：目录段精确匹配 thirdparty、third_party、vendor 者 MUST NOT 进入 manifest files；非 vendored 路径的收集行为 MUST NOT 变化。

#### Scenario: vendored 文件不入 manifest

- **WHEN** 仓内存在 thirdparty/x/a.py、third_party/y/b.py、vendor/z/c.py 且执行 scope=full 收集
- **THEN** 三者均不在 manifest files 数组，其余源码文件收集行为不变

#### Scenario: window 档同样生效

- **WHEN** scope=window 的变更面收集命中 vendored 路径改动
- **THEN** 该路径同样不入 manifest

### Requirement: 评审提示词如实描述收集范围

评审提示词 MUST 如实描述 manifest 路径性质（已排除测试/生成物/vendored 第三方目录），MUST NOT 一律宣称「manifest 路径是产品代码」；对漏出排除表但带 fenix-ignore 标注且理由为保持上游同步的文件，复核规则 MUST 指示不出题（只记录不上报）。

#### Scenario: 漏出文件按标注不出题

- **WHEN** 待审文件不在 vendored 目录但文件内带 fenix-ignore 标注且理由为保持上游同步
- **THEN** 评审只记录该事实、不上报缺陷条目