## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: tests/test_verification_report_commit.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/verify_report.py：ensure_verification_report 全部 ok 出口（present/resynthesized/synthesized）对 spec/changes/<spec>/verification-report.md 做 pathspec 精确的 git add+commit（subprocess，add 与 commit 同 pathspec，照 core/archive_commit.py 惯例）；present 出口（验证 Agent 已写报告、框架未落盘）同样触发入库；提交失败只落 WARNING（附 stderr 摘要）、不影响函数返回值与验证主流程；报告已入库且内容无变化时静默跳过（nothing to commit 不落 WARNING）
- [ ] 1.2 core/verify_report.py：提交信息采用「[fenix] <spec>: verification-report 入库」形态；确认不触碰 core/pm_engine/spec_integrity.py 的 spec_has_content 判定（verification-report.md 保持不计入内容认可名单）

## 2. 测试

- [ ] 2.1 tests/test_verification_report_commit.py：覆盖四类场景——报告落盘后触发单文件 git 提交（含 present 路径）、git 命令失败时仅 WARNING 且主流程不受影响、提交 pathspec 严格限于本报告文件（不卷入其它 spec 在途文件）、报告已入库且无变化时重复放行不落 WARNING
- [ ] 2.2 回归既有验证报告合成相关测试，确认验证 Agent 写与框架合成两路行为不变