# Proposal: 修复 improve-verify-adjudication 验证发现的缺陷

## Why

`improve-verify-adjudication` 的验证报告发现产品缺陷，导致验证未通过。详见 `openspec/changes/improve-verify-adjudication/verification-report.md` 的「真实产品 Bug」部分。

## What Changes

修复验证报告中列出的真实产品缺陷。实现者应先阅读父 SPEC 的 `verification-report.md`，定位每个真实产品 Bug 的根因并修复；伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内。

## Impact

- **代码**：按验证报告修复真实产品缺陷
- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过
