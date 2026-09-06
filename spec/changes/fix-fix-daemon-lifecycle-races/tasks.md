# Tasks: 修复 fix-daemon-lifecycle-races 验证发现的缺陷

## 1. 复核失败场景有效性（先于一切修复）

- [ ] 1.1 逐条核对 `spec/changes/fix-daemon-lifecycle-races/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为/DOM 是否相符；断言与产品不符属场景缺陷——修场景文件，不改产品代码；确属产品行为不符才进入第 2 步

## 2. 修复真实产品缺陷（仅当复核确认为真 Bug）

- [ ] 2.1 按 `verification-report.md` 的「真实产品 Bug」定位根因并修复；场景缺陷则直接修正场景文件

## 3. 验证与打包

- [ ] 3.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过
- [ ] 3.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
- [ ] 3.3 执行 `bash scripts/package.sh` 生成最新扩展包
