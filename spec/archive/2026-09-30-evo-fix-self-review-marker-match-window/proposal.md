# Proposal: 自省失败 marker 匹配窗口收敛

## 问题背景

2026-09-24 日报把完全成功的实现 run impl-fix-codefix-wipgate-defer-1790135672-a2 误计为失败样本（marker=预算耗尽），失败数报 2 实为 1。根因：_classify_run 对 type=result 终态不读 is_error/subtype，对 result 全文做 _BUSINESS_FAIL_PATTERNS 裸词子串匹配——成功摘要中段的功能词复述（实拍「预算耗尽发一次性 warning」，位于第 692/1382 字符）被当成失败声明。这是同族根因第二次显形（2026-09-17 自省 5/7 误报已修过全文件扫描面），marker 路径的裸词全文匹配仍未收敛。

## 方案概述

把 _business_fail_marker 的匹配窗口限定在 result 文本前 100 字符的失败声明区：

1. 词表 _BUSINESS_FAIL_PATTERNS 不动、_classify_run 结构不动，仅收窄匹配窗口（模块级常量）。
2. 假成功抓取语义保持——开头即声明失败的 result 终态仍判 failed（evo-add-self-review-run-semantics 的核心语义与全部 pinned 用例不推翻）。
3. _signal_evidence 终态邻近 3 行护栏不动（test_signal_fallback_when_no_marker 锁定的兜底通道不收窄）。

## 影响范围

- 修改 core/self_review.py：_business_fail_marker 匹配窗口
- 修改 tests/test_self_review_result_based_classification.py：新增中段功能词不降级回归，与既有声明形态用例成对锁边界

## 非目标

- 不跳过成功终态的 marker 判定——那会让 scheduling-showcase 型「exit 0 假成功」重新计为 succeeded，推翻 02d6cf1c。
- 不改 _signal_evidence 为仅 error 终态行匹配——会推翻无信息 result 的信号兜底 pinned 语义。
- 不做词表标点形态约束（如「预算耗尽，…」）——中文失败声明标点不统一，位置窗口比形态约束鲁棒。
