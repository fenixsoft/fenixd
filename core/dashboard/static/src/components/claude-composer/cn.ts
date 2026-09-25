// cn — 极简 className 组合器。迁移自 claudecodeui lib/utils 的 cn（clsx +
// tailwind-merge），fenixd 无对应依赖，组件内字符串拼接足够（claude-msg 同款
// 处置：模板字符串拼 className）。
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
