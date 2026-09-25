/** Tailwind 仅服务于迁移组件（claude-msg / claude-composer）：
 *  - 不含 preflight（避免重置 antd 全局样式）
 *  - darkMode 用 class 且全站不加 dark 类（dark: 变体不生效，保持亮色）
 *  - 颜色映射 claudecodeui（shadcn）的 HSL 语义变量，定义在 .claude-msg-pane 容器
 *  （add-session-composer 2.4：content 扩入 claude-composer——CLI 有 content
 *   配置时不启用自动内容检测，不扩则新组件类名静默不进 tailwind.gen.css） */
module.exports = {
  content: [
    './src/components/claude-msg/**/*.{ts,tsx}',
    './src/components/claude-composer/**/*.{ts,tsx}',
  ],
  darkMode: ['class'],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
