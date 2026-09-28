## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/verify_report.py
  kind: reference
- path: tests/test_push_closeout_report_commit.py
  kind: new
- path: tests/test_verification_report_commit.py
  kind: reference
```

## 1. push 收口报告入库

- [x] 1.1 core/pm_engine/engine.py：approve_push（约 :2600）在 _push_lock 内、_archive_auto_commit()（:2664）之前、transition(pushed)（:2673）之前，对本 spec 的 spec/changes/<spec>/verification-report.md 调用 core.verify_report 的 _commit_verification_report（函数内延迟导入防装载环；调用外层 try/except 全兜底记 push-closeout 前缀 WARNING；git add/commit 失败由函数内部捕获、WARNING 落 verify_report 通道，均不阻断 pushed 落定）
- [x] 1.2 core/verify_report.py：为跨模块复用补 docstring 声明第二消费方（push 收口），或抽薄包装；不改既有行为与签名语义

## 2. 测试

- [x] 2.1 tests/test_push_closeout_report_commit.py：报告在盘且未入库/有修改时 push → 产生仅含该单文件的 commit（pathspec 精确：其他 spec 在途草案与 staged 内容不受牵连）且 pushed 正常落定
- [x] 2.2 tests/test_push_closeout_report_commit.py：幂等（已入库无变化静默跳过零 WARNING）、报告缺失、非 git 项目、git 失败四分支均不阻断 pushed 且重入不重复提交
- [x] 2.3 回归自检：tests/test_verification_report_commit.py、tests/test_verify_report_gate.py 与 tests/test_pm_engine_dispatch_fixes.py 相关既有用例全绿，验证放行出口四处调用行为不变