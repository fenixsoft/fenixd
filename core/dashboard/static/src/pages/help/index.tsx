/**
 * 帮助中心（add-dashboard-help-center D4/D5）
 *
 * 桌面端：左侧文档目录（选中高亮）+ 右侧 Markdown 正文。
 * 移动端（<768px）：正文上方抽屉式目录切换（Drawer）。
 * URL query 同步当前文档：`?doc=<name>`，缺省 README.md，刷新/直链可还原。
 * 正文 mermaid 代码块动态 import 按需渲染；相对链接改为页内切换：
 * 纯文档名 → 切换文档；`doc.md#锚点` → 切换文档后滚动到小节；
 * `#锚点` → 当前文档页内滚动（heading 按 GitHub slug 规则注入 id）。
 */
import { Empty, Menu, Skeleton, Alert, Drawer, Button, Card } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import { isValidElement, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PageContainer } from '@ant-design/pro-components';
import type { Components } from 'react-markdown';

import { getHelpDocs, getHelpDoc } from '@/services/dashboard';
import type { HelpDocMeta, HelpDocItem } from '@/services/dashboard';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { useIsMobile } from '@/hooks/useIsMobile';

const DEFAULT_DOC = 'README.md';

function getDocFromUrl(): string {
  try {
    const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
    return params.get('doc') || DEFAULT_DOC;
  } catch {
    return DEFAULT_DOC;
  }
}

function setDocInUrl(name: string) {
  const base = window.location.hash.split('?')[0] || '#/';
  const query = name === DEFAULT_DOC ? '' : `?doc=${encodeURIComponent(name)}`;
  if (`${base}${query}` !== window.location.hash) {
    window.location.hash = `${base}${query}`;
  }
}

// ── Mermaid 渲染 ────────────────────────────────────────────────────

let mermaidIdCounter = 0;

/** 动态 import mermaid：首次调用时初始化，后续复用实例。 */
let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => m.default);
  }
  return mermaidPromise;
}

async function renderMermaid(code: string, container: HTMLDivElement) {
  try {
    const mermaid = await getMermaid();
    const id = `mermaid-${++mermaidIdCounter}`;
    // 初始化（幂等，重复调用无害）；neutral 主题配色低饱和，适合文档场景；
    // 字号统一 14px（sequence 族字号独立于 themeVariables，须单独设）
    mermaid.initialize({
      startOnLoad: false,
      theme: 'neutral',
      // strict（默认级别）：帮助文档 mermaid 图无 click 交互/图内 HTML 需求，
      // 保持 HTML/事件净化，避免文档内容引入外部内容时放大为 XSS 面
      securityLevel: 'strict',
      themeVariables: { fontSize: '14px' },
      sequence: { actorFontSize: 14, messageFontSize: 14, noteFontSize: 14 },
    });
    const { svg } = await mermaid.render(id, code);
    container.innerHTML = svg;
  } catch (err) {
    // 渲染失败回退显示原始代码（D3 规定：不白屏）
    container.innerHTML = `<pre style="background:#f5f5f5;padding:12px;border-radius:4px;overflow:auto"><code>${code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>`;
  }
}

// ── MermaidBlock：拦截 language-mermaid code 块 ────────────────────

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current && code) {
      void renderMermaid(code, ref.current);
    }
  }, [code]);
  return <div ref={ref} style={{ margin: '12px 0', minHeight: 40, display: 'flex', justifyContent: 'center' }} />;
}

// ── 锚点支持：heading id 注入 + 锚点滚动 ───────────────────────────

/** 提取 React 子节点的纯文本（heading 文本 → slug 用）。 */
function nodeText(node: any): string {
  if (node == null || node === false || node === true) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join('');
  if (typeof node === 'object' && node.props) return nodeText(node.props.children);
  return '';
}

/** GitHub 风格 slug：小写、去标点（保留 Unicode 字母/数字/空格/连字符/下划线）、空格转连字符。 */
function githubSlug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s+/g, '-');
}

// 重复标题 slug 去重计数（GitHub 规则：同名依次追加 -1、-2…）。
// buildHelpComponents 每轮重建时重置；heading 内以 useRef 缓存首次分配结果，重渲染不重复递增。
let slugCounts = new Map<string, number>();

function allocHeadingId(base: string): string {
  const n = slugCounts.get(base) ?? 0;
  slugCounts.set(base, n + 1);
  return n === 0 ? base : `${base}-${n}`;
}

/** 平滑滚动到文档内锚点；锚点不存在时静默。 */
function scrollToAnchor(anchor: string) {
  try {
    document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch {
    // 元素未挂载等异常：静默
  }
}

/** heading 组件工厂：保留原字号样式，注入 GitHub slug id（重复标题按 -1/-2 去重，锚点跳转目标）。 */
function headingComponent(Tag: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6', style: CSSProperties) {
  return function Heading({ children }: any) {
    // slug 仅分配一次并缓存于 ref：重渲染不重复递增计数，id 保持稳定
    const idRef = useRef<string | null>(null);
    if (idRef.current === null) idRef.current = allocHeadingId(githubSlug(nodeText(children)));
    return (
      <Tag id={idRef.current} style={{ ...style, scrollMarginTop: 76 }}>
        {children}
      </Tag>
    );
  };
}

// ── MarkdownComponents：扩展 markdownComponents，拦截 mermaid + 帮助文档链接 ──

function buildHelpComponents(onNavigate: (docName: string, anchor?: string) => void, docs: HelpDocMeta[]): Components {
  const docNames = new Set(docs.map((d) => d.name));
  slugCounts = new Map(); // 新一轮文档渲染：重置同名标题去重计数
  return {
    ...markdownComponents,
    code({ className, children, ...props }: any) {
      const isMermaid = className === 'language-mermaid';
      if (isMermaid) {
        const codeStr = String(children).replace(/\n$/, '');
        return <MermaidBlock code={codeStr} />;
      }
      // 普通代码块（非 mermaid）：保持等宽字体展示
      return (
        <code className={className} style={{ background: '#f4f4f4', padding: '2px 4px', borderRadius: 3, fontSize: 13 }} {...props}>
          {children}
        </code>
      );
    },
    // mermaid 代码块：code 覆盖返回的 MermaidBlock 根节点是 div，
    // 留在 pre 内会形成 <pre><div> 非法嵌套（pre 仅允许 phrasing content），
    // 这里直接返回图容器使其脱离 pre；其余代码块原样渲染 pre
    pre({ children }: any) {
      if (isValidElement(children) && children.type === MermaidBlock) {
        return children;
      }
      return <pre>{children}</pre>;
    },
    // heading 注入 GitHub slug id（页内锚点跳转目标）；字号样式同 markdownComponents
    h1: headingComponent('h1', { fontSize: 18, fontWeight: 600 }),
    h2: headingComponent('h2', { fontSize: 16, fontWeight: 600 }),
    h3: headingComponent('h3', { fontSize: 14, fontWeight: 600 }),
    h4: headingComponent('h4', { fontSize: 14, fontWeight: 400 }),
    h5: headingComponent('h5', { fontSize: 14, fontWeight: 400 }),
    h6: headingComponent('h6', { fontSize: 14, fontWeight: 400 }),
    a({ href, children, ...rest }: any) {
      // 纯锚点（#xxx，排除 SPA 路由 #/）：当前文档页内滚动
      if (href && href.startsWith('#') && !href.startsWith('#/') && href.length > 1) {
        return (
          <a
            href={href}
            onClick={(e) => { e.preventDefault(); scrollToAnchor(href.slice(1)); }}
            style={{ color: '#1677ff', cursor: 'pointer' }}
            {...rest}
          >
            {children}
          </a>
        );
      }
      // 拦截指向帮助文档的相对链接（如 ./01-quick-start.md、08-config.md#hooks）
      if (href && !href.startsWith('http') && !href.startsWith('mailto:')) {
        let docPart = href;
        let anchor = '';
        const hashIdx = href.indexOf('#');
        if (hashIdx >= 0) {
          anchor = href.slice(hashIdx + 1);
          docPart = href.slice(0, hashIdx);
        }
        let target: string | null = null;
        if (docNames.has(docPart)) {
          target = docPart;
        } else {
          // 尝试去掉 ./ 前缀
          const cleaned = docPart.replace(/^\.\//, '');
          if (docNames.has(cleaned)) target = cleaned;
        }
        if (target) {
          return (
            <a
              href={`#${window.location.hash.split('?')[0].replace('#', '')}?doc=${encodeURIComponent(target)}`}
              onClick={(e) => { e.preventDefault(); onNavigate(target!, anchor || undefined); }}
              style={{ color: '#1677ff', cursor: 'pointer' }}
              {...rest}
            >
              {children}
            </a>
          );
        }
      }
      // 其它链接：原样渲染
      return <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>;
    },
  };
}

// ── 主组件 ──────────────────────────────────────────────────────────

export default function HelpPage() {
  const isMobile = useIsMobile();
  const [docs, setDocs] = useState<HelpDocMeta[]>([]);
  const [currentDoc, setCurrentDoc] = useState<string>(getDocFromUrl());
  const [docData, setDocData] = useState<HelpDocItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [docLoading, setDocLoading] = useState(false);
  const [error, setError] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 加载文档清单
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await getHelpDocs();
        if (!cancelled) setDocs(d.docs || []);
      } catch {
        if (!cancelled) setDocs([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // URL hash 变更 → 同步文档选择
  useEffect(() => {
    const handler = () => {
      const name = getDocFromUrl();
      if (name !== currentDoc) setCurrentDoc(name);
    };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, [currentDoc]);

  // 加载单篇文档
  useEffect(() => {
    if (!currentDoc || !docs.length) return;
    let cancelled = false;
    (async () => {
      setDocLoading(true);
      setError('');
      try {
        const d = await getHelpDoc(currentDoc);
        if (!cancelled) setDocData(d);
      } catch (err) {
        if (!cancelled) {
          setDocData(null);
          setError(err instanceof Error ? err.message : '文档加载失败');
          // 加载失败时丢弃暂存的跨文档锚点，避免残留锚点在后续无关文档上误触发滚动
          pendingAnchorRef.current = null;
        }
      } finally {
        if (!cancelled) setDocLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [currentDoc, docs]);

  // 文档目录项点击
  const handleDocChange = useCallback((name: string) => {
    setCurrentDoc(name);
    setDocInUrl(name);
    setDrawerOpen(false);
  }, []);

  // 跨文档锚点跳转：待滚动锚点暂存，内容就绪后消费（见下方 effect）
  const pendingAnchorRef = useRef<string | null>(null);

  // 页内相对链接导航回调（可携带锚点：doc.md#anchor）
  const onNavigate = useCallback((name: string, anchor?: string) => {
    handleDocChange(name);
    if (!anchor) return;
    if (name === currentDoc) {
      // 同文档：内容已在渲染，等一帧后滚动
      requestAnimationFrame(() => scrollToAnchor(anchor));
    } else {
      // 跨文档：暂存锚点，等新文档加载渲染完成（滚动 effect 消费）
      pendingAnchorRef.current = anchor;
    }
  }, [handleDocChange, currentDoc]);

  // 文档内容就绪后执行待滚动锚点（跨文档锚点跳转）
  useEffect(() => {
    if (docLoading || !docData) return;
    const anchor = pendingAnchorRef.current;
    if (!anchor) return;
    pendingAnchorRef.current = null;
    requestAnimationFrame(() => scrollToAnchor(anchor));
  }, [docData, docLoading]);

  // 依赖 docData：文档内容轮次变化时重建 components（同步重置 slug 去重计数）
  const helpComponents = useMemo(() => buildHelpComponents(onNavigate, docs), [onNavigate, docs, docData]);

  // 菜单项
  const menuItems = useMemo(() => docs.map((d) => ({
    key: d.name,
    label: d.title,
  })), [docs]);

  const renderContent = () => {
    if (loading) return <Skeleton active paragraph={{ rows: 6 }} />;
    if (!docs.length) return <Empty description="暂无帮助文档" />;
    if (docLoading) return <Skeleton active paragraph={{ rows: 8 }} />;
    if (error) return <Alert type="error" message="文档加载失败" description={error} />;
    if (!docData) return <Empty description="文档内容为空" />;
    return (
      <Markdown remarkPlugins={[remarkGfm]} components={helpComponents}>
        {docData.content || ''}
      </Markdown>
    );
  };

  // 移动端布局：正文 + 顶部目录切换 Drawer
  if (isMobile) {
    return (
      <PageContainer breadcrumbRender={false} header={{ title: '帮助' }}>
        <Button
          icon={<MenuOutlined />}
          onClick={() => setDrawerOpen(true)}
          style={{ marginBottom: 12 }}
        >
          文档目录
        </Button>
        <Drawer
          title="文档目录"
          placement="left"
          width={260}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          styles={{ body: { padding: 0 } }}
        >
          <Menu
            mode="inline"
            selectedKeys={[currentDoc]}
            items={menuItems}
            onClick={({ key }) => handleDocChange(key)}
            style={{ borderRight: 'none' }}
          />
        </Drawer>
        <Card style={{ fontSize: 14, lineHeight: 1.65 }} styles={{ body: { padding: '12px 16px' } }}>
          {renderContent()}
        </Card>
      </PageContainer>
    );
  }

  // 桌面端布局：目录与正文同处一张圆角白底卡片
  return (
    <PageContainer breadcrumbRender={false} header={{ title: '帮助' }}>
      <Card styles={{ body: { padding: 0 } }}>
        <div style={{ display: 'flex' }}>
          {/* 左侧目录 */}
          <div
            style={{
              width: 240,
              flexShrink: 0,
              borderRight: '1px solid #f0f0f0',
              padding: '16px 0',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, padding: '0 16px 12px', color: '#595959' }}>
              文档目录
            </div>
            <Menu
              mode="inline"
              selectedKeys={[currentDoc]}
              items={menuItems}
              onClick={({ key }) => handleDocChange(key)}
              style={{ borderRight: 'none' }}
            />
          </div>
          {/* 右侧正文 */}
          <div style={{ flex: 1, minWidth: 0, padding: '24px 32px', fontSize: 14, lineHeight: 1.65 }}>
            {renderContent()}
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}