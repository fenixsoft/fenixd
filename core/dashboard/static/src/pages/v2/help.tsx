// /v2/help — v2 帮助页（redesign-dashboard-v2-ui 2.5）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/help.html
// （分组目录 sticky + Markdown 正文双栏磁贴）。目录分组按真实文档清单推导
// （README → 总览；NN- 前缀编号手册按序；其余 → 专题），不内联原型假想组；
// 正文复用现产 markdown-shared 渲染链（react-markdown + remarkGfm +
// markdownComponents/SafeLink，同 SpecDocModal 单源）。URL query ?doc= 同步
// 当前文档，直链/刷新可还原（口径同现产 help 页）。
//
// 2026-11-06 用户指令三则（原型豁免点随指令修订）：
// 1. 页底改白（V2Page variant="white"，v2.less `.v2-page.v2-white`）；
// 2. 页标题「帮助中心」收编全站统一标题栏控件（PageTitleBar titleBar 槽位，
//    自画 V2TitleBand 退役）；移动端标题落顶栏（2026-11-06 二次指令：移动端
//    行壳位退役，标题/「目录」filters 按钮均经 HeaderSlot/actionsRender 落
//    global header，Drawer 触发语义不变）；
// 3. 正文标题去重：DocPane 不再渲染自动 doc.title（后端 title 本就从
//    markdown 首个一级标题解析，与正文 H1 同文重复），正文首行即文档自身
//    H1（slug 锚点不受影响，headingComponent 照常注入 id）。
import { Alert, Button, Drawer, Skeleton, Spin } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import type { Components, ExtraProps } from 'react-markdown';
import type { ComponentProps, CSSProperties, ReactElement, ReactNode } from 'react';
import remarkGfm from 'remark-gfm';
import { useSearchParams } from '@umijs/max';
import { useIsMobile } from '@/hooks/useIsMobile';
import { getHelpDoc, getHelpDocs } from '@/services/dashboard';
import type { HelpDocItem, HelpDocMeta } from '@/services/dashboard';
import { isPageAnchor, markdownComponents, SafeLink } from '@/pages/projects/components/SpecDocModal';
import { PageTitleBar } from '@/components/PageTitleBar';
import { V2Page } from './shared';
import { useV2IsMobile } from './theme';

const DEFAULT_DOC = 'README.md';

// SafeLink 宽联合断言（同现产 help 页习语）
const SafeLinkComp = SafeLink as React.ComponentType<React.AnchorHTMLAttributes<HTMLAnchorElement>>;

const HELP_REMARK_PLUGINS = [remarkGfm];

// ── 锚点支持：heading id 注入 + 页内/跨文档跳转（对齐现产 help 页能力。
//    fix fe9522204a72：原自定义 a 分支条件 `!href.startsWith('#') &&
//    isPageAnchor(href)` 两子句互斥恒假成死代码，锚点与相对文档链接全部落入
//    SafeLink 兜底——该管线不注入 heading id、锚点仅 preventDefault 不定位、
//    站点相对链接降级纯文本，页内滚动与跨文档切换全部失效）──

/** nodeText 入参的最小结构：渲染树节点的鸭子类型形状（React 19 下元素 props
 * 收紧为 unknown 无法直接下钻，以 children 形状参数化，口径同现产 help 页）。 */
type MdNodeLike =
  | string
  | number
  | boolean
  | null
  | undefined
  | readonly MdNodeLike[]
  | ReactElement<{ children?: MdNodeLike }>;

/** 提取 React 子节点的纯文本（heading 文本 → slug 用）。 */
function nodeText(node: MdNodeLike): string {
  if (node == null || node === false || node === true) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join('');
  if (typeof node === 'object' && 'props' in node && node.props) return nodeText(node.props.children);
  return '';
}

/** GitHub 风格 slug：小写、去标点（保留 Unicode 字母/数字/空格/连字符/下划线）、
 * 空格转连字符；纯标点标题剔空后回退 "section"，避免产出 id=""（口径同现产）。 */
function githubSlug(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s+/g, '-');
  return slug || 'section';
}

/** 重复标题 slug 去重（GitHub 规则：同名依次追加 -1、-2…）。counts Map 由
 * buildV2HelpComponents 闭包内每轮新建（随 components 生命周期重置），渲染期
 * 不写模块级可变量。 */
function allocHeadingId(counts: Map<string, number>, base: string): string {
  const n = counts.get(base) ?? 0;
  counts.set(base, n + 1);
  return n === 0 ? base : `${base}-${n}`;
}

/** 平滑滚动到文档内锚点；锚点不存在时静默。v2 帮助页为文档级滚动（.v2-page
 * 无定高、.v2-doc 无 overflow，目录 sticky 依赖窗口滚动），scrollIntoView
 * 滚动最近滚动祖先即窗口，无需容器定位。 */
function scrollToAnchor(anchor: string) {
  try {
    document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch {
    // 元素未挂载等异常：静默
  }
}

/** heading 组件工厂：字号样式同 markdownComponents（v2 页视觉零变化），注入
 * GitHub slug id（锚点跳转目标）；slug 仅分配一次（useState 惰性初始化，重渲染
 * 不重复递增，口径同现产 help 页 item 3b810b5fda58）。scrollMarginTop 留出
 * 跳转落点呼吸（与目录 sticky top 16 同值）。 */
function headingComponent(Tag: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6', style: CSSProperties, slugCounts: Map<string, number>) {
  return function Heading({ children }: { children?: ReactNode }) {
    const [id] = useState(() => allocHeadingId(slugCounts, githubSlug(nodeText(children as MdNodeLike))));
    return (
      <Tag id={id} style={{ ...style, scrollMarginTop: 16 }}>
        {children}
      </Tag>
    );
  };
}

/** v2 帮助页 components：扩展 markdownComponents——heading 注入 slug id；a 拦截
 * 纯锚点（页内滚动）与命中文档清单的相对链接（切换文档，可携 #anchor）。 */
function buildV2HelpComponents(onNavigate: (docName: string, anchor?: string) => void, docs: HelpDocMeta[]): Components {
  const docNames = new Set(docs.map((d) => d.name));
  const slugCounts = new Map<string, number>();
  return {
    ...markdownComponents,
    h1: headingComponent('h1', { fontSize: 24, fontWeight: 600 }, slugCounts),
    h2: headingComponent('h2', { fontSize: 16, fontWeight: 600 }, slugCounts),
    h3: headingComponent('h3', { fontSize: 14, fontWeight: 600 }, slugCounts),
    h4: headingComponent('h4', { fontSize: 14, fontWeight: 400 }, slugCounts),
    h5: headingComponent('h5', { fontSize: 14, fontWeight: 400 }, slugCounts),
    h6: headingComponent('h6', { fontSize: 14, fontWeight: 400 }, slugCounts),
    // node 剔除（passNode 注入的 hast 元数据不透传到 <a>/SafeLink，同现产口径）
    a({ node: _node, href, children, ...rest }: ComponentProps<'a'> & ExtraProps) {
      // 纯锚点（#xxx，排除 SPA 路由 #/ 与裸 #）：当前文档页内平滑滚动。判定复用
      // isPageAnchor 单一口径源；本管线已注入 heading slug id，不能交由兜底
      // SafeLinkComp 承接（其管线无 id，锚点分支仅拦截原生跳转不做定位）
      if (href && isPageAnchor(href)) {
        // {...rest} 前置：href/onClick 置于展开之后，拦截逻辑不被同名透传属性覆盖
        return (
          <a
            {...rest}
            href={href}
            onClick={(e) => { e.preventDefault(); scrollToAnchor(href.slice(1)); }}
            style={{ color: 'var(--ant-color-link)', cursor: 'pointer' }}
          >
            {children}
          </a>
        );
      }
      // 相对文档链接（./NN-x.md、NN-y.md#sec 等）：# 拆分后按文档清单校验
      // （纯文档名或去 ./ 前缀后命中才拦截；SPA 路由 #/ 与外链不命中清单、自然
      // 落兜底），命中即切换文档并可携锚点滚动
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
          const cleaned = docPart.replace(/^\.\//, '');
          if (docNames.has(cleaned)) target = cleaned;
        }
        if (target) {
          return (
            <a
              {...rest}
              href={href}
              onClick={(e) => { e.preventDefault(); onNavigate(target!, anchor || undefined); }}
              style={{ color: 'var(--ant-color-link)', cursor: 'pointer' }}
            >
              {children}
            </a>
          );
        }
      }
      // 其余链接：SafeLink 协议白名单兜底（口径同现产渲染链单源）
      return <SafeLinkComp href={href} {...rest}>{children}</SafeLinkComp>;
    },
  };
}

/** 按真实清单推导分组：README → 总览；NN- 前缀 → 手册（编号序）；其余 → 专题。 */
function groupDocs(docs: HelpDocMeta[]): Array<{ group: string; items: HelpDocMeta[] }> {
  const readme = docs.filter((d) => /^readme/i.test(d.name));
  const numbered = docs
    .filter((d) => /^\d{2}-/.test(d.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  const topics = docs.filter((d) => !/^readme/i.test(d.name) && !/^\d{2}-/.test(d.name));
  const out: Array<{ group: string; items: HelpDocMeta[] }> = [];
  if (readme.length) out.push({ group: '总览', items: readme });
  if (numbered.length) out.push({ group: '使用手册', items: numbered });
  if (topics.length) out.push({ group: '专题', items: topics });
  return out;
}

function Toc({
  docs,
  currentDoc,
  onDocChange,
}: {
  docs: HelpDocMeta[];
  currentDoc: string;
  onDocChange: (name: string) => void;
}) {
  const groups = useMemo(() => groupDocs(docs), [docs]);
  return (
    <div className="v2-bento" data-proto-id="hp-toc" style={{ width: 250, flexShrink: 0, padding: 10, position: 'sticky', top: 16 }}>
      {groups.map((g) => (
        <div key={g.group}>
          <div className="v2-toc-group">{g.group}</div>
          {g.items.map((it) => (
            <div
              key={it.name}
              role="button"
              tabIndex={0}
              onClick={() => onDocChange(it.name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') onDocChange(it.name);
              }}
              className={`v2-toc-item${it.name === currentDoc ? ' on' : ''}`}
              aria-current={it.name === currentDoc ? 'page' : undefined}
            >
              {it.title}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function DocPane({
  doc,
  loading,
  docs,
  onNavigate,
}: {
  doc: HelpDocItem | null;
  loading: boolean;
  docs: HelpDocMeta[];
  onNavigate: (docName: string, anchor?: string) => void;
}) {
  // 依赖 doc：文档内容轮次变化时重建 components（heading 组件函数身份变化即
  // 重挂载，同步重置 slug 去重计数，口径同现产 help 页）
  const components = useMemo(() => buildV2HelpComponents(onNavigate, docs), [onNavigate, docs, doc]);
  // 移动端阅读内边距 28→16（2026-11-07 用户指令「帮助页左右间距 0px」定稿：
  // 页面容器经 v2.less 全幅已 0（负 margin 抵消 layout 内嵌），此 28px 为文档
  // 自身阅读内边距——正文贴 0 会顶屏幕玻璃边，按全局 16px 口径收窄；桌面 28 不变）
  const isMobile = useIsMobile();
  const docPad = isMobile ? '24px 16px 32px' : '24px 28px 32px';
  if (loading) {
    return (
      <div className="v2-bento" data-proto-id="hp-doc" style={{ flex: 1, minWidth: 0, padding: docPad }}>
        <Skeleton active title paragraph={{ rows: 8 }} />
      </div>
    );
  }
  if (!doc) return null;
  return (
    <div className="v2-bento v2-doc" data-proto-id="hp-doc" style={{ flex: 1, minWidth: 0, padding: docPad, minHeight: 320 }}>
      {/* 正文标题只此一份（2026-11-06 用户指令「内容区域标题重复」）：原 DocPane
          顶部自动 doc.title 行已删——后端 title 本就从 markdown 首个一级标题
          解析（help_routes._help_doc_title），与正文 H1 同文双显；保留正文 H1
          （headingComponent 注入 slug id，锚点跳转目标不受影响） */}
      <Markdown remarkPlugins={HELP_REMARK_PLUGINS} components={components}>
        {doc.content}
      </Markdown>
    </div>
  );
}

export default function V2HelpPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [docs, setDocs] = useState<HelpDocMeta[]>([]);
  const [docsError, setDocsError] = useState('');
  const [loading, setLoading] = useState(true);
  const [docData, setDocData] = useState<HelpDocItem | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const mobile = useV2IsMobile();
  const currentDoc = searchParams.get('doc') || DEFAULT_DOC;
  // 跨文档锚点跳转：待滚动锚点暂存，文档内容就绪后由下方 effect 消费
  // （口径同现产 help 页 pendingAnchorRef）
  const pendingAnchorRef = useRef<string | null>(null);

  const handleDocChange = useCallback(
    (name: string) => {
      // 改选文档即作废在途跨文档锚点：暂存锚点只对发起跳转的那篇文档生效，
      // 否则前一篇的锚点会在新选文档就绪后被误消费（GitHub slug 常见同名小节）。
      // 本清除先于 onNavigate 的暂存写入执行，不影响正常跨文档锚点跳转
      pendingAnchorRef.current = null;
      const next = new URLSearchParams(searchParams);
      if (name === DEFAULT_DOC) next.delete('doc');
      else next.set('doc', name);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  // 页内相对链接导航回调（可携带锚点：doc.md#anchor）。本管线无 mermaid 异步
  // 渲染（markdownComponents 代码块为静态 pre/code），布局即时稳定，等一帧后
  // 直接滚动即可（口径较现产 help 页免 mermaid 等待）
  const onNavigate = useCallback(
    (name: string, anchor?: string) => {
      handleDocChange(name);
      if (!anchor) return;
      if (name === currentDoc) {
        requestAnimationFrame(() => scrollToAnchor(anchor));
      } else {
        pendingAnchorRef.current = anchor;
      }
    },
    [handleDocChange, currentDoc],
  );

  // 文档内容就绪后消费待滚动锚点（跨文档锚点跳转）。docData.name 归属校验防
  // 陈旧响应语境下误消费：快速连续跳转时前一篇响应可能后落地，此时不消费、
  // 保留锚点等正确文档就绪（口径同现产 help 页滚动 effect）
  useEffect(() => {
    if (docLoading || !docData) return;
    if (docData.name !== currentDoc) return;
    const anchor = pendingAnchorRef.current;
    if (!anchor) return;
    pendingAnchorRef.current = null;
    requestAnimationFrame(() => scrollToAnchor(anchor));
  }, [docData, docLoading, currentDoc]);

  // 移动形态：目录抽屉化——选中文档后收起抽屉（渐进披露）
  const pickDoc = useCallback(
    (name: string) => {
      handleDocChange(name);
      setTocOpen(false);
    },
    [handleDocChange],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getHelpDocs()
      .then((d) => {
        if (!cancelled) {
          setDocs(d.docs || []);
          setDocsError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setDocsError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDocLoading(true);
    getHelpDoc(currentDoc)
      .then((d) => {
        if (!cancelled) {
          setDocData(d);
          setDocLoading(false);
        }
      })
      .catch(() => {
        // 单篇失败回退缺省文档（清 query），避免整页卡死在不存在文档上
        if (!cancelled) {
          setDocLoading(false);
          if (currentDoc !== DEFAULT_DOC) handleDocChange(DEFAULT_DOC);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [currentDoc, handleDocChange]);

  // 移动形态（prototype/m-help.html）：目录抽屉化（「目录」按钮触发——已随迁
  // 标题栏 filters 槽位，选中后收起）；正文单列；现产本无搜索入口（桌面亦无），
  // 与原型零搜索一致。页标题（2026-11-06 用户指令）经 V2Page titleBar 槽位落
  // 统一标题栏：standalone 顶栏承载「帮助中心 · N 篇文档」，移动端行壳位承载。
  return (
    <V2Page
      variant="white"
      titleBar={
        <PageTitleBar
          title="帮助中心"
          subtitle={loading ? undefined : `${docs.length} 篇文档`}
          filters={
            mobile ? (
              <Button size="small" onClick={() => setTocOpen(true)}>
                目录
              </Button>
            ) : undefined
          }
        />
      }
    >
      {docsError ? (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message="文档清单加载失败" description={docsError} />
      ) : null}
      {mobile ? (
        <>
          <Drawer
            title="文档目录"
            placement="right"
            open={tocOpen}
            onClose={() => setTocOpen(false)}
            // antd v6 弃用 width prop（→ size 仅 default/large），自定宽走
            // styles.wrapper（contentWrapperStyle 映射）承载，免控制台弃用告警
            styles={{ body: { padding: '4px 10px' }, wrapper: { width: 300 } }}
          >
            <Toc docs={docs} currentDoc={currentDoc} onDocChange={pickDoc} />
          </Drawer>
          {docLoading && !docData ? (
            <div className="v2-bento" style={{ padding: 48, textAlign: 'center' }}>
              <Spin size="large" />
            </div>
          ) : (
            <DocPane doc={docData} loading={docLoading} docs={docs} onNavigate={onNavigate} />
          )}
        </>
      ) : (
        <div data-proto-id="hp-layout" style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          <Toc docs={docs} currentDoc={currentDoc} onDocChange={handleDocChange} />
          {docLoading && !docData ? (
            <div className="v2-bento" style={{ flex: 1, padding: 48, textAlign: 'center' }}>
              <Spin size="large" />
            </div>
          ) : (
            <DocPane doc={docData} loading={docLoading} docs={docs} onNavigate={onNavigate} />
          )}
        </div>
      )}
    </V2Page>
  );
}
