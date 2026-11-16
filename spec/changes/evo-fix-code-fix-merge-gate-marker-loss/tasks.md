## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_marker_only_merge.py
  kind: new
```

## 1. 合并门守卫改造（core/code_fix.py）

- [x] 1.1 core/code_fix.py：零有效修复守卫（`if not fixed_ids or commits <= 0`，2026-11-16 工作树实测 :7923）前置「纯标记核查」——fixed=0 且 commits>0 时对批内全部提交 diff 做形态核查：新增行全部为含 `[fenix-ignore:<item_id>]` 标记本体的注释行（注释语法按 agents/code-fix.md「忽略标记」节取文件语言形态：Python/YAML `#`、TS/JS `//`、HTML/Markdown `<!-- -->` 等，可含尾随说明文字），且删除行仅为标记注释行或为空；纯标记批改走既有批合回通道并按完成收尾，批内 pending（非 ignored）条目比照现拒合回分支入 chain_skipped（保留下链重试语义，不核销不置终态）；混合批维持拒合回
- [x] 1.2 core/code_fix.py：全批 ignored 的「批按完成收尾」分支（「无需合回」完成收尾分支，2026-11-16 实测 :7924-7934 一带）接入同一核查前置段，存在纯标记提交时先合回再收尾（该分支 pending 为空，无条目处置问题），不再静默丢弃
- [x] 1.3 core/code_fix.py：拒合回路径（2026-11-16 实测 warning 在 :7942、_safe_cleanup 紧随其后）落 admin 告警留痕——含被弃提交完整 SHA、批条目 id、非标记文件清单，落痕先于 _safe_cleanup；warning 日志文案同步附 commit id
- [x] 1.4 core/code_fix.py：链 rollup 与台账注记补产物去向——「产物已合并（纯标记）/产物已弃（commit <sha>…）」；fixed>0 批、commits=0 零产物批行为零变化

## 2. 测试（新建 tests/test_code_fix_marker_only_merge.py）

- [x] 2.1 tests/test_code_fix_marker_only_merge.py：纯标记批放行场景——fixed=0+commits=1+纯标记 diff（覆盖 `<!-- -->` 形态〔对照 00162a0 实例〕与 `#` 形态〔Python 标记批〕至少各一例），断言合回成功、按完成收尾、pending 条目入 chain_skipped、rollup 注记「产物已合并（纯标记）」
- [x] 2.2 tests/test_code_fix_marker_only_merge.py：混合批反例——diff 含非标记改动（含「删除实质代码行+新增标记行」反例：删除行非标记即拒放），断言不合回、告警留痕含 commit 完整 SHA 与非标记文件清单、留痕调用先于清理
- [x] 2.3 tests/test_code_fix_marker_only_merge.py：全批 ignored 收尾路径场景——全 ignored+纯标记提交，断言先合回再收尾、success 终态不丢产物
- [x] 2.4 tests/test_code_fix_marker_only_merge.py：零行为变化回归——fixed>0 批合回、commits=0 零产物批拒合回、可修复形态 salvage 三路径行为不变断言