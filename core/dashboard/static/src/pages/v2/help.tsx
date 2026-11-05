// /v2/help — v2 帮助页（redesign-dashboard-v2-ui 2.5）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/help.html
// （分组目录 sticky + Markdown 正文双栏磁贴）。目录分组按真实文档清单推导
// （README → 总览；NN- 前缀编号手册按序；其余 → 专题），不内联原型假想组；
// 正文复用现产 markdown-shared 渲染链（react-markdown + remarkGfm +
// markdownComponents/SafeLink，同 SpecDocModal 单源）。URL query ?doc= 同步
// 当前文档，直链/刷新可还原（口径同现产 help 页）。
import { Alert, Button, Drawer, Skeleton, Spin } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useSearchParams } from '@umijs/max';
import { getHelpDoc, getHelpDocs } from '@/services/dashboard';
import type { HelpDocItem, HelpDocMeta } from '@/services/dashboard';
import { isPageAnchor, markdownComponents, SafeLink } from '@/pages/projects/components/SpecDocModal';
import { V2Page, V2TitleBand } from './shared';
import { useV2IsMobile } from './theme';

const DEFAULT_DOC = 'README.md';

// SafeLink 宽联合断言（同现产 help 页习语）
const SafeLinkComp = SafeLink as React.ComponentType<React.AnchorHTMLAttributes<HTMLAnchorElement>>;

const HELP_REMARK_PLUGINS = [remarkGfm];

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

function DocPane({ doc, loading }: { doc: HelpDocItem | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="v2-bento" data-proto-id="hp-doc" style={{ flex: 1, minWidth: 0, padding: '24px 28px 32px' }}>
        <Skeleton active title paragraph={{ rows: 8 }} />
      </div>
    );
  }
  if (!doc) return null;
  return (
    <div className="v2-bento v2-doc" data-proto-id="hp-doc" style={{ flex: 1, minWidth: 0, padding: '24px 28px 32px', minHeight: 320 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.3 }}>{doc.title}</span>
      </div>
      <div style={{ marginTop: 12 }}>
        <Markdown
          remarkPlugins={HELP_REMARK_PLUGINS}
          components={{
            ...markdownComponents,
            // 相对链接页内切换（纯文档名 → 切换；锚点 → 交由 markdownComponents
            // 兜底），外链经 SafeLink（现产渲染链单源）
            a: (props) => {
              const href = props.href || '';
              if (href && !href.startsWith('#') && !href.startsWith('http') && isPageAnchor(href)) {
                return <SafeLinkComp {...props} />;
              }
              const Comp = (markdownComponents.a || SafeLinkComp) as React.ComponentType<
                React.AnchorHTMLAttributes<HTMLAnchorElement>
              >;
              return <Comp {...props} />;
            },
          }}
        >
          {doc.content}
        </Markdown>
      </div>
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

  const handleDocChange = useCallback(
    (name: string) => {
      const next = new URLSearchParams(searchParams);
      if (name === DEFAULT_DOC) next.delete('doc');
      else next.set('doc', name);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

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

  // 移动形态（prototype/m-help.html）：目录抽屉化（标题行「目录」按钮触发，
  // 选中后收起）；正文单列；现产本无搜索入口（桌面亦无），与原型零搜索一致。
  return (
    <V2Page>
      <V2TitleBand
        title="帮助中心"
        subtitle={loading ? undefined : `${docs.length} 篇文档`}
        right={
          mobile ? (
            <Button size="small" onClick={() => setTocOpen(true)}>
              目录
            </Button>
          ) : undefined
        }
      />
      <div style={{ marginTop: 18 }}>
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
              <DocPane doc={docData} loading={docLoading} />
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
              <DocPane doc={docData} loading={docLoading} />
            )}
          </div>
        )}
      </div>
    </V2Page>
  );
}
