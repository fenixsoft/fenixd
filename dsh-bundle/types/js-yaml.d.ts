/**
 * js-yaml.d.ts — js-yaml 4.3+ 的 exports 指向无类型的 dist/js-yaml.mjs，
 * 而 @types/js-yaml 未入 devDependencies（离线环境不可即装）。helper 只用
 * `load(text): unknown` 一面，最小化声明（与 dsh-peers.d.ts 同为编译期面）。
 */

declare module "js-yaml" {
  /** 解析 YAML 文档；失败抛异常，调用方自行窄化与容错。 */
  export function load(text: string, options?: unknown): unknown;
}
