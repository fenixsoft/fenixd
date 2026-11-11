# DSH 右键菜单隐身回归：消解器文本匹配误伤交互面（2026-11-11）

## 结论
`fenix-dsh-dashboard-bridge` 的 workspace 原生提示消解器（`wsTooltip.ts createNativeTipSuppressor`，fix-workspace-tip-overlap 批次）按「body 直子 portal 的 textContent 含已装项目名」隐藏节点。文件右键菜单加入「在 Fenix 项目「X」中定位」项后，**每颗文件菜单的 textContent 都内嵌项目名** → 菜单 portal 挂载即被 `display:none`，用户侧表现为「文件右键弹不出来」，且 console 无任何报错（菜单装配正常，只是被隐藏）。

## 修复模式
消解器 hideIfMatch 增交互面守卫：portal 自身或后代命中
`[role="menu"],[role="menuitem"],[role="dialog"],[role="alertdialog"],[role="listbox"],[role="option"]` 即跳过。
注意 querySelector 不含节点自身，menu wrapper 是 body 直子且自带 role=menu —— 必须 matches + querySelector 双查。

## 测试教训（两次踩坑）
1. **DOM 在场 ≠ 可见**：E2E 用 querySelector 存在性 + textContent + `el.click()` 断言菜单——display:none 节点全部照常命中、click() 照常派发，「验证通过」的菜单从未显示过。UI 可见性断言必须 `getComputedStyle(el).display` + `getBoundingClientRect().width > 0`。
2. 静默失败路径（`failed()` 不打日志）+ 无报错 ≠ 无 bug；用户 console 里的良性 WARNING 也可能是线索——本次该 WARNING 正是消解器打出的（命中名单里就有项目名）。

## 排查链路（可复用）
服务端 concat 字节验证 bundle 新旧 → 我方页面同 chip 右键 → `closest('body > *')` 取 portal 根 → computed display 'none' + textContent 含项目名 → 锁定消解器；修复后同链路断言 display 'flex' + rect 宽 >0 + 7 menu items。
