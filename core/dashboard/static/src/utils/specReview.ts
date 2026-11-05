// 评审相关 blocked 前缀清单单源（code-review item 801f9399dba8）：现产
// projects/list.tsx 与 v2/specDetail.tsx 原先各持同值副本、靠「同 list.tsx」
// 类注释互锚（refreshPolicy.ts 头注释点名的同款反模式），后端 re_review
// 白名单扩充时漏改一处会使评审类 blocked 的「重新评审」入口静默缺失，
// 收敛到本模块（对齐 @/utils/duration 的抽单源先例）。

// 与后端 re_review 白名单（core/pm_engine/spec_review.py
// SpecReviewManager.re_review）逐字同源：后端扩展前缀时仅需同步本清单。
export const SPEC_REVIEW_BLOCKED_PREFIXES = ['spec-review-rejected:', 'spec-review-incomplete:'];
