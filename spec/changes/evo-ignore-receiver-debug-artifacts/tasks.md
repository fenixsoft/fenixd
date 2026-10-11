## Deliverables

```yaml
- path: .gitignore
  kind: modify
```

## 1. ignore 面扩展

- [ ] 1.1 .gitignore 末尾追加 `.debug/` 条目与中文注释（说明为 receiver 真机调试帧存/日志落点、复发型产物前置免疫，风格对齐既有 tailwind.gen.css 条目——当前末条、同为复发型产物 + 成因注释；评审更正：build-win-configure.log 系 potplayer-base 仓案例非本仓条目）
- [ ] 1.2 git status --porcelain -uall 全表对照盘点运行时产物目录：如存在第二个同类 untracked 产物目录一并追加并注明依据；当前核查实测仓库内无第二标的

## 2. 免疫验证

- [ ] 2.1 git check-ignore -v .debug/ 命中新追加条目（纯模式匹配，目录不存在亦可验）；git status --porcelain -uall 对 .debug/ 零输出（当前实测目录已不存在、天然零输出）；若落地时目录已复发存在，其下文件原路径原样存在（现场零扰动），MUST NOT 为验证而重建该目录
- [ ] 2.2 核对 .fenix/stray_untracked_registry.json：当前实测已为空 {}（原指纹 ff7ba4707455188d 条目已随 .debug/ 目录消失按「指纹消失自动复位」清除，major 升级倒计时前提随之解除）；确认不再新增 maintree_untracked_stray_stale 告警；目录未来复发后经一轮盘点（daemon 300 秒周期）不得产生新条目；若 maintree_untracked_stray_escalated 已先触发，以既有 admin 裁决 ignore_untracked_stray 收口并在结果中注明