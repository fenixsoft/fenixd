// intlText.ts — 非组件模块的 intl 单源取值 shim（i18n 修复轮 batch-A）。
//
// 背景：services/dashboard.ts 被 ~14 个 node 原生直载测试（type-stripping 直载
// .ts）与多个 esbuild SSR bundle 测试消费，`import { getIntl } from '@umijs/max'`
// 具名导入在 raw node 下链接期报错（@umijs/max 是 CJS 壳，Named export not
// found）；命名空间导入 `import * as ns from '@umijs/max'` 实测链接安全。本
// shim 三语境行为：
// - Umi 运行时：ns.getIntl 存在 → getIntl().formatMessage 正常出 en/zh；
// - esbuild + tests/fixtures/umi-max-stub.mjs alias：桩 getIntl → zh 目录表；
// - raw node：ns.getIntl undefined → 回落 zh-CN 目录表 + {name} 占位替换
//   （与桩同构），既有中文断言零改动。
// 渲染期调用（勿模块顶层求值），语言切换即时生效；先例 src/utils/format.ts。
import zhCN from '../locales/zh-CN.ts';
import * as umiMaxNs from '@umijs/max';

type IntlTextValues = Record<string, string | number>;

interface MinimalIntl {
  formatMessage: (descriptor: { id: string }, values?: IntlTextValues) => string;
}

/** {name} 占位替换（仅替换 values 中存在的键，与 umi-max-stub 同构） */
function fillTemplate(template: string, values?: IntlTextValues): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : whole,
  );
}

/** 消息 id → 当前语言文案；id 缺席目录时回退 id 本身（不抛错）。 */
export function intlText(id: string, values?: IntlTextValues): string {
  try {
    const getIntlFn = (umiMaxNs as { getIntl?: () => MinimalIntl }).getIntl;
    if (typeof getIntlFn === 'function') {
      const text = getIntlFn().formatMessage({ id }, values);
      if (typeof text === 'string' && text) return text;
    }
  } catch {
    // intl 上下文未就绪（极端早调用）按 zh 目录回落，不抛错
  }
  const table = zhCN as unknown as Record<string, string>;
  const template = Object.prototype.hasOwnProperty.call(table, id) ? table[id] : id;
  return fillTemplate(template, values);
}
