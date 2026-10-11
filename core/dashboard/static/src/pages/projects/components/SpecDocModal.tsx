import { Modal, Tabs, Spin, Empty, Alert, Button } from 'antd';
import {
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { CSSProperties, ReactElement, ReactNode } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { getSpecDoc } from '@/services/dashboard';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

export type DocType = 'proposal' | 'design' | 'tasks' | 'verification' | 'scenarios';

type DocStatus = 'loading' | 'done' | 'empty' | 'error';

interface DocCacheEntry {
  status: DocStatus;
  content?: string;
}

// 文档缓存条目上限：超出后按最旧淘汰，避免长会话跨 spec 浏览时大文本（验证报告/tasks 等）持续累积
const MAX_CACHE_ENTRIES = 50;

// 写入缓存并淘汰超限旧条目；先删后写以刷新该键的新近度（Map 迭代按插入序）
const setCacheEntry = (cache: Map<string, DocCacheEntry>, key: string, entry: DocCacheEntry) => {
  cache.delete(key);
  cache.set(key, entry);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined || oldest === key) break;
    cache.delete(oldest);
  }
};

// 缓存键拼接的单一来源：`${project}:${spec}:${doc}`。
// 读写（useMemo 取条目 / loadDoc 写入 / handleRetry 清除）必须共用本函数，
// 口径不一致时读写键错开会导致文档永远停在 Spin 态且无报错
const buildCacheKey = (project: string, spec: string, doc: string) => `${project}:${spec}:${doc}`;

interface SpecDocModalProps {
  project: string;
  spec: string | null;
  open: boolean;
  onClose: () => void;
  // 打开时定位的页签（如时间轴「verification report」链接 → 验证报告）；不传则保持上次页签
  initialDoc?: DocType;
}

// 允许的链接协议白名单
const ALLOWED_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

// 纯页内锚点判定（#xxx，排除 SPA 路由 #/ 与裸 #）：SafeLink 与帮助中心（help 页，
// 自建 a 组件做页内滚动）共用的条件口径，单一来源避免双处判定各自漂移
export const isPageAnchor = (href: string): boolean =>
  href.startsWith('#') && !href.startsWith('#/') && href.length > 1;

// 自定义链接组件：非白名单协议不输出可点击链接
// （导出供帮助中心等其它 markdown 场景的链接兜底复用，保持协议白名单口径一致）
export const SafeLink: Components['a'] = ({ node: _node, href, children, ...props }) => {
  if (!href) {
    return <span>{children}</span>;
  }

  // 页内锚点（#xxx，排除 SPA 路由 #/ 与裸 #）：仅拦截原生跳转，不做页内滚动定位。
  // 本组件管线不给标题生成 id（markdownComponents 的 heading 只定样式，无 rehype-slug），
  // 页内锚点没有跳转目标；需要真实锚点跳转的场景（帮助中心）自建 a 组件并注入 heading
  // slug id，不经过本组件。
  // 仍须 preventDefault：本应用基于 hash 路由，原生跳转会把 location.hash 从 #/... 改写成
  // #xxx，被路由当作路径变更导致当前页面被切走
  if (isPageAnchor(href)) {
    return (
      <a href={href} onClick={(e) => e.preventDefault()} {...props}>
        {children}
      </a>
    );
  }

  // SPA 路由链接（#/）：保持原生跳转
  if (href.startsWith('#/')) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  }

  // 裸 #（如 LLM 生成 markdown 里的 [占位](#)）：与上方页内锚点同理须 preventDefault，
  // 原生跳转会清空 location.hash，被路由当作路径变更切回缺省页导致当前页面被切走
  if (href === '#') {
    return (
      <a href={href} onClick={(e) => e.preventDefault()} {...props}>
        {children}
      </a>
    );
  }

  // 站点相对链接（index.md、./design.md 等无协议路径）：解析后仍指向本站，
  // 而 dashboard 没有承载这些仓库相对路径的页面，target=_blank 只会新开站点
  // 404 页——降级为纯文本作站内反馈；协议相对链接（//host）解析为外部站点，
  // 不在此拦截
  if (!/^[a-z][a-z0-9+.-]*:/i.test(href) && !href.startsWith('//')) {
    return <span>{children}</span>;
  }

  try {
    // 绝对链接与协议相对链接基于当前页面解析，解析结果仍须过协议白名单
    const url = new URL(href, window.location.href);
    if (ALLOWED_PROTOCOLS.has(url.protocol)) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    }
  } catch {
    // 无效 URL，作为纯文本处理
  }

  // 非白名单协议或无效 URL，渲染为纯文本
  return <span>{children}</span>;
};

// 内联代码 chip（GitHub 风格）：`xx` 渲染为灰底圆角等宽片段，与正文可区分
const codeChipStyle: CSSProperties = {
  padding: '0.15em 0.4em',
  borderRadius: 4,
  background: 'rgba(135,131,120,0.15)',
  color: '#1677ff',
  fontFamily: 'SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace',
  fontSize: '0.9em',
};

// 从表格 children 的表头子树（thead/tr/th）递归收集文本，用于表头指纹识别与
// th 定宽查找（同一取文本口径）。只下钻表头元素：remark-gfm 把 GFM 表格首行
// 渲染为 <thead><tr><th>、表体在 <tbody> 内，指纹特征词必须落在表头才算命中
// ——若连表体全文一起匹配，普通表格正文恰好出现「编号」「摘要」等特征词就会
// 被误套知识表定宽布局。表头内的行内格式元素（`code`、**strong** 等 GFM 内联
// 语法产物及 SafeLink 降级 span）同样下钻取纯文本，含格式的表头不失宽。
const HEADER_TEXT_ELEMENTS = new Set([
  'thead', 'tr', 'th',
  'code', 'strong', 'em', 'del', 'a', 'span', 'br',
]);
const collectTableText = (node: ReactNode): string => {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(collectTableText).join('');
  if (isValidElement(node)) {
    const el = node as ReactElement<{ children?: ReactNode }>;
    if (!HEADER_TEXT_ELEMENTS.has(String(el.type))) return '';
    return collectTableText(el.props.children);
  }
  return '';
};

// 知识真相源表格的列宽定义：按表头指纹（两个特征词同时出现）识别表格类型，
// 经 Context 由 table 组件下发给 th 定宽；无命中的表格不设宽不受影响。
const KNOWLEDGE_TABLE_WIDTHS: { fingerprint: [string, string]; widths: Record<string, string> }[] = [
  // 总目录「能力域」四列表：30/42/8/20（总和 100%，fixed 布局按比例归一）
  { fingerprint: ['能力域', '能力数量'], widths: { 能力域: '30%', 简介: '42%', 能力数量: '8%', 更新时间: '20%' } },
  // 域导航「能力页」三列表：28/52/20
  { fingerprint: ['能力页', '简介'], widths: { 能力页: '28%', 简介: '52%', 更新时间: '20%' } },
  // ADR 索引「编号/状态/摘要」三列表：15/15/70
  { fingerprint: ['编号', '摘要'], widths: { 编号: '15%', 状态: '15%', 摘要: '70%' } },
];
const TableWidthContext = createContext<Record<string, string> | null>(null);

// 自定义 components 配置（验证结论等其它 markdown 场景复用）
// 标题/正文/列表显式定字号，覆盖容器继承（容器多为 13px）
export const markdownComponents: Components = {
  a: SafeLink,
  // react-markdown v10 无 inline prop：以 className（language-*）或内容含换行
  // 判围栏块（CommonMark 围栏内容恒以换行结尾），其余按内联 chip 渲染
  code: ({ node: _node, className, children, ...props }) => {
    const isBlock =
      (typeof className === 'string' && className.includes('language-')) ||
      /\n/.test(String(children));
    if (isBlock) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return <code style={codeChipStyle}>{children}</code>;
  },
  pre: ({ node: _node, children, ...props }) => (
    <pre
      style={{
        background: '#f6f8fa',
        padding: '12px 16px',
        borderRadius: 6,
        overflowX: 'auto',
        fontSize: 13,
        lineHeight: 1.6,
      }}
      {...props}
    >
      {children}
    </pre>
  ),
  h1: ({ children }) => <h1 style={{ fontSize: 24, fontWeight: 600 }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: 16, fontWeight: 600 }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: 14, fontWeight: 600 }}>{children}</h3>,
  h4: ({ children }) => <h4 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h4>,
  h5: ({ children }) => <h5 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h5>,
  h6: ({ children }) => <h6 style={{ fontSize: 14, fontWeight: 400 }}>{children}</h6>,
  p: ({ children }) => <p style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</p>,
  ul: ({ children }) => <ul style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ fontSize: 14, lineHeight: 1.9 }}>{children}</ol>,
  // antd reset 去掉了表格默认边框，这里补齐：通宽 + 灰色细线网格。
  // 知识真相源表格（指纹命中）加 table-layout:fixed——auto layout 下 th width
  // 只是提示（如总和 105% 会被浏览器重分配），fixed 才能按定义精确控宽
  table: ({ node: _node, children, ...props }) => {
    const head = collectTableText(children);
    const hit = KNOWLEDGE_TABLE_WIDTHS.find((w) => w.fingerprint.every((k) => head.includes(k)));
    return (
      <TableWidthContext.Provider value={hit ? hit.widths : null}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            margin: '12px 0',
            ...(hit ? { tableLayout: 'fixed' as const } : {}),
          }}
          {...props}
        >
          {children}
        </table>
      </TableWidthContext.Provider>
    );
  },
  // 列宽经 TableWidthContext 由所在 table 下发（td 跟随所在列宽，无需单设）；
  // 取文本与 table 指纹识别同口径（collectTableText），行内格式表头不失宽
  th: ({ node: _node, children, ...props }) => {
    const widths = useContext(TableWidthContext);
    const width = widths ? widths[collectTableText(children).trim()] : undefined;
    return (
      <th
        style={{
          border: '1px solid #e8e8e8',
          padding: '8px 12px',
          textAlign: 'left',
          background: '#fafafa',
          fontSize: 14,
          ...(width ? { width } : {}),
        }}
        {...props}
      >
        {children}
      </th>
    );
  },
  td: ({ node: _node, children, ...props }) => (
    <td style={{ border: '1px solid #e8e8e8', padding: '8px 12px', fontSize: 14 }} {...props}>
      {children}
    </td>
  ),
};

export default function SpecDocModal({ project, spec, open, onClose, initialDoc }: SpecDocModalProps) {
  const [activeTab, setActiveTab] = useState<DocType>('proposal');

  // 指定 initialDoc 时，每次打开定位到该页签（验证报告链接入口）
  useEffect(() => {
    if (open && initialDoc) setActiveTab(initialDoc);
  }, [open, initialDoc]);
  const { modalProps, maximizeButton } = useMaximizeModal({
    defaultWidth: '80%',
    defaultBodyHeight: 'calc(80vh - 80px)',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', overflow: 'hidden' },
    centered: true,
  });
  const cacheRef = useRef<Map<string, DocCacheEntry>>(new Map());
  const [cacheVersion, setCacheVersion] = useState(0);

  // 当前 project+spec+doc 的缓存键（含 project 维度：组件跨项目常驻挂载，cacheRef 存活，
  // 不同项目的同名 spec 必须各自独立，避免互相串用文档内容）
  const cacheKey = useMemo(() => {
    if (!spec) return '';
    return buildCacheKey(project, spec, activeTab);
  }, [project, spec, activeTab]);

  // 当前缓存条目
  const currentEntry = useMemo(() => {
    if (!cacheKey) return undefined;
    return cacheRef.current.get(cacheKey);
  }, [cacheKey, cacheVersion]);

  const loadDoc = useCallback(async () => {
    if (!spec) return;
    const key = buildCacheKey(project, spec, activeTab);

    // 检查缓存：loading 表示该 key 已有在途请求，不重复加载
    const cached = cacheRef.current.get(key);
    if (cached && cached.status === 'loading') {
      return;
    }

    // done 缓存仅作首屏占位：文档（验证报告/任务清单等）可能已渐进更新，后台 revalidate 后替换展示
    const revalidate = cached?.status === 'done';

    if (!revalidate) {
      // 设置 loading 状态
      setCacheEntry(cacheRef.current, key, { status: 'loading' });
      setCacheVersion((v) => v + 1);
    }

    try {
      const d = await getSpecDoc(project, spec, activeTab);
      if (d.found) {
        setCacheEntry(cacheRef.current, key, { status: 'done', content: d.content || '' });
      } else {
        setCacheEntry(cacheRef.current, key, { status: 'empty' });
      }
    } catch {
      // revalidate 失败时保留旧内容，避免清空已展示文档
      if (!revalidate) {
        setCacheEntry(cacheRef.current, key, { status: 'error' });
      }
    } finally {
      setCacheVersion((v) => v + 1);
    }
  }, [project, spec, activeTab]);

  useEffect(() => {
    if (!open || !spec) return;
    void loadDoc();
  }, [open, spec, loadDoc]);

  // 切换页签时触发加载
  const handleTabChange = useCallback((key: string) => {
    setActiveTab(key as DocType);
  }, []);

  // 重试加载
  const handleRetry = useCallback(() => {
    if (!spec) return;
    const key = buildCacheKey(project, spec, activeTab);
    cacheRef.current.delete(key);
    void loadDoc();
  }, [project, spec, activeTab, loadDoc]);

  const renderContent = () => {
    if (!currentEntry) {
      return (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin />
        </div>
      );
    }

    switch (currentEntry.status) {
      case 'loading':
        return (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <Spin />
          </div>
        );
      case 'empty':
        return <Empty description="无此文档" />;
      case 'error':
        return (
          <Alert
            type="error"
            message="文档加载失败"
            description={
              <Button type="link" onClick={handleRetry}>
                点击重试
              </Button>
            }
          />
        );
      case 'done':
      default:
        return (
          <div
            style={{
              height: '100%',
              overflow: 'auto',
              fontSize: 13,
              lineHeight: 1.65,
            }}
          >
            <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {currentEntry.content || ''}
            </Markdown>
          </div>
        );
    }
  };

  return (
    <Modal
      title={
        <MaximizeTitle text={`${spec || ''} 文档`} button={maximizeButton} />
      }
      open={open}
      onCancel={onClose}
      footer={null}
      {...modalProps}
    >
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          { key: 'proposal', label: '需求背景' },
          { key: 'design', label: '详细设计' },
          { key: 'tasks', label: '任务清单' },
          { key: 'scenarios', label: '测试场景清单' },
          { key: 'verification', label: '验证报告' },
        ]}
      />
      <div style={{ flex: 1, minHeight: 0 }}>{renderContent()}</div>
    </Modal>
  );
}
