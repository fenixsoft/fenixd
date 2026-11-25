/**
 * umi 约定 loading 文件（src/loading.tsx），一处定义、两个消费方：
 * 1. 启动期全屏过渡——config.ts `initialState.loading: '@/loading'` 注入
 *    InitialStateProvider，覆盖 getInitialState（拉项目菜单）期间的空白；
 * 2. 路由 lazy chunk 下载期——preset-umi appData 自动探测本文件并注入
 *    renderer-react 路由 Suspense fallback（useStream 恒开），覆盖深链
 *    首次进入详情页时页面 chunk 下载期的空白。
 * 禁止 import antd：本文件随入口 chunk 加载，引组件库会显著拖慢首屏。
 * 视觉样式在 global.less「启动加载过渡」块，CSS 变量随 data-fenix-theme
 * 自动换档（与 umi.css head 占位 #root:empty 同款衔接）。
 *
 * 文案双语（i18n 宿主跟随轮）：本组件渲染早于 IntlProvider/语言偏好
 * bootstrap（useIntl 不可用），按 localePreference 纯函数独立判定——嵌入态
 * 宿主初始档（URL locale 参数）优先，回退 fenix.locale 偏好链（与首帧防
 * 闪烁脚本同口径，en-US → 'Loading'，其余 → '加载中'）。
 */
import { embedLocaleParam } from './utils/embedMount.ts';
import { readLocalePreference, resolveTarget } from './utils/localePreference.ts';

function bootLocaleText(): string {
  const target = embedLocaleParam() ?? resolveTarget(readLocalePreference());
  return target === 'en-US' ? 'Loading' : '加载中';
}

export default function Loading() {
  return (
    <div className="fenix-boot-loading">
      <div className="fenix-boot-loading-ring" />
      <div className="fenix-boot-loading-text">{bootLocaleText()}</div>
    </div>
  );
}
