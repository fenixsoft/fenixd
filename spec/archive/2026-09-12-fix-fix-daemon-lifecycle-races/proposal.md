# Proposal: 修复 fix-daemon-lifecycle-races 验证发现的缺陷

## Why

`fix-daemon-lifecycle-races` 的验证报告发现产品缺陷，导致验证未通过。详见 `spec/changes/fix-daemon-lifecycle-races/verification-report.md` 的「真实产品 Bug」部分。

## What Changes

第一步必须复核失败场景的有效性（fix-fake-failure-first）：验证场景自身可能存在断言缺陷（如英文状态字面量 vs 产品中文渲染、不存在的选择器、错误的前置数据），伪失败修复应改场景文件而非产品代码。复核确认为真实产品 Bug 后，先阅读父 SPEC 的 `verification-report.md`，定位每个真实产品 Bug 的根因并修复。

## Impact

- **代码**：按复核结论修复场景缺陷或真实产品缺陷
- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过
