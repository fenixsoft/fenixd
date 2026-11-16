# v0.1.4 真机实测：Windows 写侧三连修与裸 PATH 窗口（反馈 items 4-8）

**来源**：用户 v0.1.4 Windows 11 真机全量部署实录反馈第 4–8 条（2026-11-16）。

## 结论与落点

1. **os.rename → os.replace 归一（item 4，WinError 183 类）**：Windows 目标已存在时
   `os.rename` 抛 `[WinError 183]`（POSIX 静默替换语义不成立）。全库审计 4 处：
   `core/admin_store.py:397`、`:627`（告警写入，实测命中 ×4，fail-open 静默丢告警）、
   `core/self_review.py:120` 全部改 `os.replace`；`core/pm_engine/engine.py:2440`
   的 rename 是"摘除到唯一临时名"语义（目标必不存在），Windows 安全，**不改**。
   教训：**Windows 路径上写"临时文件 + rename"原子写必须用 os.replace**；code review
   时把 os.rename 视为 Windows 缺陷候选。
2. **STATE.md 空读撕窗守卫（item 6，×6/轮）**：写侧已是原子 replace（core/fs_utils），
   但 Windows 读者（AV/索引器/SMB 抖动）仍会读出空白。守卫落
   `StateParser._read_text_tear_guarded`：空白但 size>0 → 重试 3×30ms；耗尽 →
   warning + 空串（上层既有"跳过本轮"自愈兜底）；size==0 合法空文件零开销直返。
   测试 `tests/test_state_tear_guard.py` 4 用例。
3. **pm.push.retry_backoff_seconds None 日志降级（item 7，×3）**：键未配置/注释示例
   是设计内缺省 → 静默（DEBUG）；非 None 非法形态（字符串/短 list）保留 WARNING。
   `core/pm_engine/engine.py` `_push_lock` 配置段。
4. **裸 PATH 首启窗口消除（item 8）**：产品 `install_unit(root, env=...)` 注入半边
   早已落地（fix-spawn-attribution-hardening 4805b019f），实测只见到检测半边
   （env_defect）的根因是**手册 §8 教的是两步形态**（install_unit → 手工注册表写 →
   restart）。手册已改一步形态为主（env= 传服务 PATH 最小集 + DSH_HOME +
   LLM_API_KEY），手工注册表块降级为"已装服务补配/审计"用途。
5. **无 remote 验收仓库 push_failed 属预期（item 5）**：手册 §9.0 已加注——
   `[push_failed — 已停止自动重试]` 时 status 仍 done、problems 不计数；配 origin
   可消除，纯本地可无视。

## 验证

- Linux 全量回归 183 passed / 6 skipped（win32-only 照跳）；tear guard 4/4。
- 裸 PATH 窗口：过机验证待用户下一轮实测（G1-26~28 同窗口）。
