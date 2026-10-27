// 迁移自 claudecodeui src/components/chat/view/subcomponents/Markdown.tsx（精简版）：
// - 去 i18n（按钮提示改为中文文案）
// - 去 usePaletteOps / 文件编辑器跳转（文件链接保留样式，不做拦截）
// - 去 MermaidDiagram（mermaid 代码块按普通代码高亮显示）
// - 去 useTheme（dashboard 全站亮色，语法高亮固定 oneLight）
import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

import { normalizeInlineCodeFences } from './chatFormatting';
import { ALLOWED_PROTOCOLS } from '../markdown-shared';

type MarkdownProps = {
  children: React.ReactNode;
  className?: string;
  /** Render single newlines as hard line breaks (for user-typed messages). */
  breaks?: boolean;
};

export const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    // select()/execCommand 抛异常时也要移除已插入的节点，否则透明定位的隐藏
    // textarea 会在 body 中残留累积（code-review item 8df2dd69b7bc）
    let inserted = false;
    try {
      document.body.appendChild(textarea);
      inserted = true;
      textarea.select();
      const ok = document.execCommand('copy');
      return ok;
    } finally {
      if (inserted) {
        document.body.removeChild(textarea);
      }
    }
  } catch {
    return false;
  }
};

// A usable file path contains a separator or a filename with an extension.
const looksLikeFilePath = (value?: string): value is string => {
  if (!value) return false;
  const cleaned = value.trim();
  if (!cleaned || cleaned === '#') return false;
  return /[\\/]/.test(cleaned) || /\.[a-z0-9]+$/i.test(cleaned);
};

// Extract plain text from link children so a reference rendered only as link
// text (e.g. `[src/foo.ts]()` with an empty href) can still be recognized.
const childrenToText = (children: React.ReactNode): string => {
  if (typeof children === 'string' || typeof children === 'number') {
    return String(children);
  }
  if (Array.isArray(children)) {
    return children.map(childrenToText).join('');
  }
  if (React.isValidElement(children)) {
    return childrenToText((children.props as { children?: React.ReactNode }).children);
  }
  return '';
};

type CodeBlockProps = {
  node?: any;
  className?: string;
  children?: React.ReactNode;
  /** Set by the custom `pre` renderer: this code element is a fenced/indented block. */
  forceBlock?: boolean;
};

// `node` is destructured out so react-markdown's hast node never reaches the DOM.
const CodeBlock = ({ node: _node, className, children, forceBlock, ...props }: CodeBlockProps) => {
  const [copied, setCopied] = useState(false);
  // 「已复制」2 秒回退定时器的句柄：覆盖旧定时器，并在组件卸载时清理，
  // 避免悬挂定时器在卸载后仍触发 setState。
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(copiedTimerRef.current), []);
  // Fenced blocks carry a trailing newline in the tree; trim it so the
  // highlighter doesn't render an empty final line.
  const raw = (Array.isArray(children) ? children.join('') : String(children ?? '')).replace(/\n$/, '');
  // react-markdown v9+ dropped the `inline` prop: block code is whatever the
  // `pre` renderer hands us (forceBlock). Multiline is kept as a safety net.
  const shouldInline = !forceBlock && !/[\r\n]/.test(raw);

  if (shouldInline) {
    return (
      <code
        className={`whitespace-pre-wrap break-words rounded-md border border-border/70 bg-muted px-1.5 py-0.5 font-mono text-[0.875em] text-foreground ${className || ''}`}
        {...props}
      >
        {children}
      </code>
    );
  }

  // [\w+#-] 覆盖 c++ / objective-c / c# 等含非字母数字字符的语言标注
  const match = /language-([\w+#-]+)/.exec(className || '');
  const language = match ? match[1] : 'text';
  const languageLabel = language.charAt(0).toUpperCase() + language.slice(1);

  return (
    <div className="group my-3 overflow-hidden rounded-xl border border-border bg-muted/50 shadow-sm">
      {/* Label row shares the block's background — no divider, ChatGPT-style */}
      <div className="flex items-center justify-between px-4 pt-2">
        <span className="select-none text-xs text-muted-foreground">{languageLabel}</span>
        <button
          type="button"
          onClick={() =>
            copyToClipboard(raw).then((success) => {
              if (success) {
                setCopied(true);
                clearTimeout(copiedTimerRef.current);
                copiedTimerRef.current = setTimeout(() => setCopied(false), 2000);
              }
            })
          }
          className={`rounded-md p-1 transition-opacity focus-visible:opacity-100 ${
            copied
              ? 'text-green-600 opacity-100'
              : 'text-muted-foreground opacity-0 hover:text-foreground group-hover:opacity-100'
          }`}
          title={copied ? '已复制' : '复制代码'}
          aria-label={copied ? '已复制' : '复制代码'}
        >
          {copied ? (
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path
                fillRule="evenodd"
                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 010 1.414z"
                clipRule="evenodd"
              />
            </svg>
          ) : (
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path>
            </svg>
          )}
        </button>
      </div>

      <SyntaxHighlighter
        language={language}
        style={oneLight}
        customStyle={{
          margin: 0,
          borderRadius: 0,
          fontSize: '0.8125rem',
          lineHeight: 1.6,
          padding: '0.5rem 1rem 1rem',
          // The container owns the background so the label row and code read as one panel.
          background: 'transparent',
        }}
        codeTagProps={{
          style: {
            fontFamily:
              'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            background: 'transparent',
          },
        }}
      >
        {raw}
      </SyntaxHighlighter>
    </div>
  );
};

const markdownComponents = {
  code: CodeBlock,
  // Fenced/indented code arrives as <pre><code>. Re-render the child CodeBlock
  // with `forceBlock` so it always gets the block treatment (react-markdown v9+
  // no longer passes an `inline` flag), and skip the outer <pre> so Tailwind
  // Typography doesn't wrap the highlighter in a second shell.
  pre: ({ children }: { children?: React.ReactNode }) => {
    const child = Array.isArray(children) ? children.find(React.isValidElement) : children;
    if (React.isValidElement(child) && child.type === CodeBlock) {
      return <CodeBlock {...(child.props as CodeBlockProps)} forceBlock />;
    }
    return <>{children}</>;
  },
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-3 border-l-2 border-primary/50 pl-4 italic text-muted-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-t border-border" />,
  p: ({ children }: { children?: React.ReactNode }) => <div className="mb-2 last:mb-0">{children}</div>,
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mb-2 list-outside list-disc space-y-1 pl-5 marker:text-current last:mb-0">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mb-2 list-outside list-decimal space-y-1 pl-5 marker:text-current last:mb-0">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="[&>div:last-child]:mb-0 [&>div]:mb-1">{children}</li>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-border">
      <table className="my-0 min-w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: React.ReactNode }) => <thead className="bg-muted/60">{children}</thead>,
  tr: ({ children }: { children?: React.ReactNode }) => (
    <tr className="[&:last-child>td]:border-b-0">{children}</tr>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border-b border-border px-3 py-2 text-left font-semibold text-foreground">{children}</th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border-b border-border/60 px-3 py-2 align-top">{children}</td>
  ),
};

export function Markdown({ children, className, breaks = false }: MarkdownProps) {
  const content = normalizeInlineCodeFences(String(children ?? ''));
  const remarkPlugins = useMemo(
    () =>
      (breaks
        ? [remarkGfm, [remarkMath, { singleDollarTextMath: false }], remarkBreaks]
        : [remarkGfm, [remarkMath, { singleDollarTextMath: false }]]) as any,
    [breaks],
  );
  const rehypePlugins = useMemo(() => [rehypeKatex], []);

  const components = useMemo(
    () => ({
      ...markdownComponents,
      a: ({ href, children: linkChildren }: { href?: string; children?: React.ReactNode }) => {
        const linkText = childrenToText(linkChildren);
        // fileRef 回退链展开（项目清单禁嵌套三元，code-review item 1a1bff97634f）
        let fileRef: string | undefined;
        if (looksLikeFilePath(href)) {
          fileRef = href;
        } else if (looksLikeFilePath(linkText)) {
          fileRef = linkText;
        }

        if (fileRef && !/^(https?:|mailto:|tel:|data:)/i.test(href || '')) {
          // 工作区文件引用：dashboard 无编辑器跳转能力，渲染为带路径提示的链接样式
          return (
            <span
              className="cursor-default text-blue-600"
              title={fileRef}
            >
              {linkChildren}
            </span>
          );
        }

        // 协议白名单（消费 markdown-shared 的共享导出 ALLOWED_PROTOCOLS，与
        // SafeLink 同源，避免两份白名单各自漂移，见 code-review item
        // e571142420c3）：AI 生成的正文或工具输出可能携带 javascript: 等危险协
        // 议链接，非白名单协议一律降级为纯文本，杜绝点击执行任意脚本。href 交给
        // URL 解析器统一处理大小写与制表符/换行混淆（java\tscript:）、首尾空白；
        // 相对路径无协议，基于当前页面解析后落在本站 http(s) 白名单内，维持既有
        // 可点击渲染。不直接复用 SafeLink 组件：其会把站点相对路径降级为纯文本，
        // 与本组件的既有可点击行为不同
        let linkUrl: URL | undefined;
        try {
          linkUrl = new URL(href || '', window.location.href);
        } catch {
          // 无效 URL：按纯文本处理
        }
        if (!linkUrl || !ALLOWED_PROTOCOLS.has(linkUrl.protocol)) {
          return <span>{linkChildren}</span>;
        }

        return (
          <a
            href={href}
            className="text-blue-600 hover:underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            {linkChildren}
          </a>
        );
      },
    }),
    [],
  );

  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components as any}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
