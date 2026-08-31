# Tasks: improve-v3-spec-doc-markdown

## 1. 渲染依赖与组件抽离

- [ ] 1.1 安装 react-markdown + remark-gfm（版本与 React 19 兼容），构建验证
- [ ] 1.2 文档弹窗抽为 `src/pages/projects/components/SpecDocModal.tsx`（props: project/spec/open/onClose），list.tsx 改为引用
- [ ] 1.3 组件内实现三页签 + `Map` 缓存（loading/done/empty/error 四态，键 `${spec}:${doc}`）

## 2. Markdown 渲染与安全

- [ ] 2.1 react-markdown + remark-gfm 渲染 content（GFM：标题/列表/表格/代码块/任务勾选）
- [ ] 2.2 链接协议白名单：自定义 `a` 渲染，非 http/https/mailto 不输出可点击链接
- [ ] 2.3 三态 UI：加载 Spin / 空态 Empty"无此文档" / 错误 Alert + 重试

## 3. 验证

- [ ] 3.1 浏览器走查 spec Scenario：页签懒加载与缓存（network 面板核对请求数）、GFM 渲染效果、空态/错误态
- [ ] 3.2 对照 v1 文档弹窗同 spec 同页签：内容语义一致
- [ ] 3.3 console 零错误；`npm run build` 通过；dist 提交
