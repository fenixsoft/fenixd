// embedBridge.ts — embed 态 iframe → dsh 宿主单向请求桥（add-dsh-new-session-button）。
//
// dsh 面板桥（fenix-dsh-dashboard-bridge）以同源前缀反代把本前端嵌进 dsh web
// 主面板/右缘页签 iframe。嵌入态下 dashboard 需要请求宿主执行「dsh 侧动作」
// （当前唯一需求：新建会话——工作区定位/创建与会话启动都是宿主侧
// uiWorkspace 能力，dashboard 自身无法触达），本模块是唯一的 iframe→宿主
// 出站通道：window.parent.postMessage，载荷形状：
//
//   { kind: 'fenix-dashboard:new-session', project: string, prompt?: string }
//
// - kind：消息鉴别常量（与桥插件 src/client/index.ts HOST_NEW_SESSION_KIND
//   双仓镜像，改一处必改另一处——两侧各自单测钉值）；
// - project：fenix 项目名（即 dsh 工作区定位的 title/basename 口径）；
// - prompt：可选会话框预填文本（SPEC 详情页「对于 XXXX SPEC：」前缀），宿主
//   经 uiWorkspace.startSession(workspaceId, { prompt }) 落入新会话输入框。
//
// 安全口径：同源反代保证 iframe 与宿主同 origin，targetOrigin 恒取本页
// origin（不广播）；宿主侧回程校验 event.origin + 载荷形状（桥侧纪律）。
//
// 非 embed 态（standalone fenix dashboard）没有宿主：恒返回 false 且零
// side-effect——按钮层已按 isEmbedMode() 隐藏，本函数是第二道门（防误调）。
//
// 零第三方 import：仅复用 embedMount 的 isEmbedMode（embedMount 本身零
// import，node type-stripping 直载测试先例不变）。

import { isEmbedMode } from './embedMount.ts';

/** iframe → 宿主「新建会话」消息 kind（桥插件 HOST_NEW_SESSION_KIND 镜像值）。 */
export const HOST_NEW_SESSION_KIND = 'fenix-dashboard:new-session';

/** 出站消息形状（prompt 缺省时不出现在载荷里，保持最小形状）。 */
export interface HostNewSessionMessage {
  kind: typeof HOST_NEW_SESSION_KIND;
  project: string;
  prompt?: string;
}

/**
 * 请求宿主新建会话。仅 embed 态且确有宿主（window.parent !== window）时
 * postMessage；返回是否真正发出（false = 非 embed/无宿主，调用方无需兜底
 * UI——按钮本就不该出现）。fire-and-forget：宿主执行结果不经本通道回传，
 * dsh 主面板视图切换本身即用户可见反馈。
 */
export function requestHostNewSession(project: string, prompt?: string): boolean {
  if (!isEmbedMode()) return false;
  if (window.parent === window) return false;
  const message: HostNewSessionMessage =
    prompt === undefined
      ? { kind: HOST_NEW_SESSION_KIND, project }
      : { kind: HOST_NEW_SESSION_KIND, project, prompt };
  window.parent.postMessage(message, window.location.origin);
  return true;
}
