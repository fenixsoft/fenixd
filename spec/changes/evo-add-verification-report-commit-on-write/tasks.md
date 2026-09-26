## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: tests/test_verification_report_commit.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/verify_report.py：ensure_verification_report 写盘成功后对 spec/changes/<spec>/verification-report.md 做 pathspec 精确的 git add+commit（subprocess，add 与 commit 同 pathspec，照 core/archive_commit.py 惯例）；提交失败只落 WARNING（附 stderr 摘要）、不影响函数返回值与验证主流程
- [ ] 1.2 core/verify_report.py：提交信息采用「[fenix] <spec>: verification-report 入库」形态；确认不触碰 core/pm_engine/spec_integrity.py 的 spec_has_content 判定（verification-report.md 保持不计入内容认可名单）

## 2. 测试

- [ ] 2.1 tests/test_verification_report_commit.py：覆盖三类场景——报告落盘后触发单文件 git 提交、git 命令失败时仅 WARNING 且主流程不受影响、提交 pathspec 严格限于本报告文件（不卷入其它 spec 在途文件）
- [ ] 2.2 回归既有验证报告合成相关测试，确认验证 Agent 写与框架合成两路行为不变