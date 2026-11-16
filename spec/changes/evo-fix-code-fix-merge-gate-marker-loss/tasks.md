## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_marker_only_merge.py
  kind: new
```

## 1. 合并门守卫改造（core/code_fix.py）

- [ ] 1.1 core/code_fix.py：零有效修复守卫（:7881 一带）前置「纯标记核查」——fixed=0 且 commits>0 时对批内全部提交 diff 做形态核查（新增行全部为 `// [fenix-ignore:<item_id>]`/`<!-- [fenix-ignore:<item_id>] -->` 注释形态），纯标记批改走既有批合回通道并按完成收尾；混合批维持拒合回
- [ ] 1.2 core/code_fix.py：全批 ignored 的「批按完成收尾」分支（:7882-7896 一带）接入同一核查前置段，存在纯标记提交时先合回再收尾，不再静默丢弃
- [ ] 1.3 core/code_fix.py：拒合回路径落 admin 告警留痕——含被弃提交完整 SHA、批条目 id、非标记文件清单，落痕先于 _safe_cleanup；warning 日志文案同步附 commit id
- [ ] 1.4 core/code_fix.py：链 rollup 与台账注记补产物去向——「产物已合并（纯标记）/产物已弃（commit <sha>…）」；fixed>0 批、commits=0 零产物批行为零变化

## 2. 测试（新建 tests/test_code_fix_marker_only_merge.py）

- [ ] 2.1 tests/test_code_fix_marker_only_merge.py：纯标记批放行场景——fixed=0+commits=1+纯标记 diff，断言合回成功、按完成收尾、rollup 注记「产物已合并（纯标记）」
- [ ] 2.2 tests/test_code_fix_marker_only_merge.py：混合批反例——diff 含非标记改动，断言不合回、告警留痕含 commit 完整 SHA 与非标记文件清单、留痕调用先于清理
- [ ] 2.3 tests/test_code_fix_marker_only_merge.py：全批 ignored 收尾路径场景——全 ignored+纯标记提交，断言先合回再收尾、success 终态不丢产物
- [ ] 2.4 tests/test_code_fix_marker_only_merge.py：零行为变化回归——fixed>0 批合回、commits=0 零产物批拒合回、可修复形态 salvage 三路径行为不变断言