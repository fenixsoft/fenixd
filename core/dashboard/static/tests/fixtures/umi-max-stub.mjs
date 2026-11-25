// '@umijs/max' 测试桩（i18n 修复轮 batch-S）。
//
// 背景：仓库把 @umijs/max 列为 devDependency（真实 Umi 构建期生成 src/.umi），
// node_modules 里并不存在该包；settings 面板 batch-S 起组件经 useIntl 取文案，
// SSR esbuild 打包（hooksPanel / knowledgeSettings / quickAssign 三测试）需要
// 一个 '@umijs/max' alias 目标才能成 bundle。本桩提供最小 getIntl/useIntl：
// - 消息表取 src/locales/zh-CN.ts（SSR 渲染 zh，与既有中文断言兼容）；
// - formatMessage 仅支持 {name} 形态 ICU 占位（本仓 settings 域只用该形态），
//   缺键回退 id，不抛错；
// - locale 恒 'zh-CN'（测试断言 zh 文案；en 档由 locales/en-US.ts 的
//   enOverrides 覆盖，生产经 Umi locale 机制切换，与本桩无关）。
import zhCN from '../../src/locales/zh-CN.ts';

function formatMessage(descriptor = {}, values = {}) {
  const id = typeof descriptor === 'string' ? descriptor : descriptor.id;
  const template = Object.prototype.hasOwnProperty.call(zhCN, id) ? zhCN[id] : id;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    values && Object.prototype.hasOwnProperty.call(values, name)
      ? String(values[name])
      : whole,
  );
}

const intl = { locale: 'zh-CN', messages: zhCN, formatMessage };

export function getIntl() {
  return intl;
}

export function useIntl() {
  return intl;
}

export const FormattedMessage = ({ id, values }) => formatMessage({ id }, values);

export default intl;
