// KnowledgeTab.tsx — 项目页「项目知识」分面（add-knowledge-atlas 4.1）
//
// 承载知识真相源只读视图：
// - active 门控：仅在选中本分面时拉取 GET /api/knowledge/index，未选中零
//   请求（对齐 QualityTab/RegressionTab/ArchitectureTab 按需加载语义）。
// - enabled 门控：GET /api/config 的 knowledge.enabled === false 时渲染禁用
//   占位（说明 + 去设置页指引），不再发其它请求。
// - 视图栈：总目录（index.md Markdown 渲染；ADR 清单只在
//   adr/index.md，见总目录「决策记录」节链接，此处不重复展示）
//   → 能力页/导航页/ADR 详情（点进拉单文件，面包屑返回总目录）。
//   （graph 关系图区已随 graphify 功能取消整段下线——2026-09-29，探测、
//   iframe 与后端 /api/knowledge/graph 下发端点一并移除。）
// - 链接导航：Markdown 相对链接（truth-source 内部路径）拦截为站内拉取，
//   经 resolveKnowledgePath 基于当前页目录归一化；外部链接走 SafeLink 白名单。
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnchorHTMLAttributes, FC, ReactNode } from 'react';
import { Breadcrumb, Button, Card, Space, Spin, Typography } from 'antd';
import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ApiError,
  getConfig,
  getKnowledgeFile,
  getKnowledgeIndex,
} from '../../../services/dashboard';
import type { KnowledgeIndexData } from '../../../services/dashboard';
import SpecDocModal, { SafeLink, markdownComponents } from './SpecDocModal';

// SafeLink 的导出类型是 Components['a']（含 undefined/string 字面量宽型），
// 运行时恒为函数组件；此处显式收窄为锚点 FC 供 JSX 复用（实现签名兼容）。
const SafeLinkAsAnchor = SafeLink as FC<
  AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }
>;

interface KnowledgeTabProps {
  project: string;
  active: boolean;
}

// ── 纯函数（node --test 覆盖）────────────────────────────────────────

/** 基于当前页目录归一化真相源内相对链接 → 白名单相对路径；越界/非法返回
 *  null（不发起请求）。currentPath 形如 'domains/pickup/x.md' 或 null（总
 *  目录，基目录为真相源根）。POSIX 语义，不触浏览器 URL。 */
export function resolveKnowledgePath(
  currentPath: string | null,
  href: string,
): string | null {
  if (!href || href.startsWith('#') || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//')) {
    return null;
  }
  const stripped = href.split('#', 1)[0];
  if (!stripped) return null;
  const baseDir = currentPath ? currentPath.replace(/[^/]*$/, '') : '';
  const segments = (baseDir + stripped).split('/');
  const out: string[] = [];
  for (const seg of segments) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      if (out.length === 0) return null; // 越出真相源根
      out.pop();
      continue;
    }
    out.push(seg);
  }
  const resolved = out.join('/');
  if (
    !resolved.startsWith('domains/') &&
    !resolved.startsWith('adr/')
  ) {
    return null;
  }
  return resolved;
}

/** 剥离 Markdown 中的 HTML 注释：marker（capability/rev/sources）是机器
 *  接口，对人类读者隐形（渲染层剥离，源文件不动）。 */
export function stripHtmlComments(md: string): string {
  return md
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** 面包屑项：target='index' 回总目录；字符串=真相源内页路径（域导航页）；
 *  null=当前层纯文本（不可点击）。 */
export interface KnowledgeCrumb {
  title: string;
  target: 'index' | string | null;
}

/** 面包屑：真相源内路径 → 层级项（含点击目标，替代裸目录路径）。
 *  'domains/<域>/<能力>.md' → [总目录→index, <域>→域导航页, <能力>→null]；
 *  'domains/<域>/_domain.md' → [总目录→index, <域>→null]（域名即当前层级）；
 *  'adr/ADR-001-x.md' → [总目录→index, ADR→adr/index.md, ADR-001-x→null]；
 *  'adr/index.md' → [总目录→index, ADR→null]（索引自身，ADR 即当前层级）。 */
export function knowledgeCrumbs(path: string): KnowledgeCrumb[] {
  const rawSegs = path
    .replace(/\.md$/, '')
    .split('/')
    .filter(Boolean);
  const isDomainNav = rawSegs[rawSegs.length - 1] === '_domain';
  const segs = rawSegs.filter((s) => s !== '_domain');
  const indexCrumb: KnowledgeCrumb = { title: '总目录', target: 'index' };
  if (segs[0] === 'adr') {
    if (segs.length === 2 && segs[1] === 'index') {
      return [indexCrumb, { title: 'ADR', target: null }];
    }
    return [
      indexCrumb,
      { title: 'ADR', target: 'adr/index.md' },
      ...segs.slice(1).map((title) => ({ title, target: null })),
    ];
  }
  return [
    indexCrumb,
    ...segs.slice(1).map((title, i, arr) => ({
      title,
      target:
        i === 0 && arr.length > 1 && !isDomainNav
          ? `domains/${title}/_domain.md`
          : null,
    })),
  ];
}

/** 归档链接派生 spec 名：'spec/archive/<YYYY-MM-DD-<名>[/]>' → '<名>'；其余
 *  （真相源页路径/外部 URL/锚点）返回 null。溯源行链接指向 spec/archive 目录，
 *  SpecDocModal 经后端 resolve_spec_dir（活跃优先、归档回退）按裸名解析。 */
export function archiveSpecName(href: string): string | null {
  const m = /^spec\/archive\/([A-Za-z0-9._-]+)\/?$/.exec(href);
  if (!m) return null;
  return m[1].replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

// ── 组件 ─────────────────────────────────────────────────────────────

type View =
  | { kind: 'index' }
  | { kind: 'page'; path: string; content: string };

export default function KnowledgeTab({ project, active }: KnowledgeTabProps) {
  const [enabledUnknown, setEnabledUnknown] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [indexData, setIndexData] = useState<KnowledgeIndexData | null>(null);
  const [view, setView] = useState<View>({ kind: 'index' });
  const [loading, setLoading] = useState(false);
  // 加载失败态（code-review item 61d229fbd494）：config/index 请求失败的
  // 错误消息；null = 无错误。与「尚未初始化」业务态区分，不互相伪装。
  const [loadError, setLoadError] = useState<string | null>(null);
  // 溯源归档链接弹出的 SPEC 文档弹窗（spec/archive/ 链接 → 剥日期 spec 名）
  const [docSpec, setDocSpec] = useState<string | null>(null);
  // 请求序号守卫（QualityTab/RegressionTab 同款）：慢响应不覆盖新视图
  const seqRef = useRef(0);

  // active 门控拉取：先 config 判 enabled，再拉 index
  const load = useCallback(async () => {
    if (!active || !project) return;
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      const cfg = await getConfig(project);
      if (seq !== seqRef.current) return;
      const on = cfg.knowledge?.enabled !== false;
      setEnabled(on);
      setEnabledUnknown(false);
      if (!on) return;
      const data = await getKnowledgeIndex(project);
      if (seq !== seqRef.current) return;
      setIndexData(data);
      setLoadError(null);
    } catch (e) {
      if (seq !== seqRef.current) return;
      setEnabled(true);
      setEnabledUnknown(false);
      setIndexData(null);
      // 记 error 态而非伪装成「尚未初始化」（code-review item 61d229fbd494）
      setLoadError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [active, project]);

  useEffect(() => {
    if (!active || !project) return;
    void load();
  }, [active, project, load]);

  // 项目切换重置视图态：组件跨项目常驻挂载（Tabs 切换不卸载子组件），
  // 上个项目残留的详情视图（view.kind='page'）会把上个项目的能力页内容
  // 串到新项目显示（冒烟实测）。
  useEffect(() => {
    setView({ kind: 'index' });
    setIndexData(null);
    setEnabledUnknown(true);
    setLoadError(null);
    setDocSpec(null);
  }, [project]);

  if (!active) return null;

  // ── 禁用占位（knowledge.enabled=false）────────────────────────────
  if (!enabledUnknown && !enabled) {
    return (
      <Card variant="borderless" data-testid="knowledge-disabled-card">
        <Space direction="vertical" size={8}>
          <Typography.Text strong>知识真相源已禁用</Typography.Text>
          <Typography.Text type="secondary" data-testid="knowledge-disabled-desc">
            本实例已在设置中关闭知识真相源（knowledge.enabled=false）。蒸馏管线不会
            运行，此处不展示知识内容；可在「系统设置 → 杂项」中重新开启。
          </Typography.Text>
        </Space>
      </Card>
    );
  }

  if (enabledUnknown || loading) {
    return (
      <Card variant="borderless" data-testid="knowledge-loading">
        <Space>
          <Spin size="small" />
          <Typography.Text type="secondary">加载知识目录…</Typography.Text>
        </Space>
      </Card>
    );
  }

  // 加载失败占位（code-review item 61d229fbd494）：明示错误 + 重试入口，
  // 不再回落到「尚未初始化」业务占位；重试复用 load（loading 态自动接管渲染）。
  if (loadError !== null) {
    return (
      <Card variant="borderless" data-testid="knowledge-load-error">
        <Space direction="vertical" size={8}>
          <Typography.Text strong>知识目录加载失败</Typography.Text>
          <Typography.Text type="secondary">{loadError}</Typography.Text>
          <Button size="small" data-testid="knowledge-retry" onClick={() => void load()}>
            重试
          </Button>
        </Space>
      </Card>
    );
  }

  const uninitialized = !indexData?.initialized;

  const openPage = async (path: string) => {
    const seq = ++seqRef.current;
    try {
      const data = await getKnowledgeFile(project, path);
      if (seq !== seqRef.current) return;
      setView({ kind: 'page', path: data.path, content: data.content });
    } catch (e) {
      if (seq !== seqRef.current) return;
      // 文件缺失等：不置全局 loadError 态，而是整页切换为 page 视图、以引用
      // 块形式提示错误（原视图被替换，可经「返回总目录」回退）
      const msg = e instanceof ApiError ? e.message : String(e);
      setView({ kind: 'page', path, content: `> 加载失败：${msg}\n` });
    }
  };

  // 站内相对链接拦截：spec/archive 归档链接 → 弹 SPEC 文档弹窗；真相源内
  // 路径 → 站内拉取；其余走 SafeLink 白名单
  const currentPath = view.kind === 'page' ? view.path : null;
  const linkComponents: Components = {
    ...markdownComponents,
    a: (props) => {
      const href = props.href || '';
      const spec = archiveSpecName(href);
      if (spec !== null) {
        return (
          <a
            href={href}
            onClick={(e) => {
              e.preventDefault();
              setDocSpec(spec);
            }}
          >
            {props.children}
          </a>
        );
      }
      const target = resolveKnowledgePath(currentPath, href);
      if (target !== null) {
        return (
          <a
            href={`#knowledge:${target}`}
            onClick={(e) => {
              e.preventDefault();
              void openPage(target);
            }}
          >
            {props.children}
          </a>
        );
      }
      return <SafeLinkAsAnchor {...props} />;
    },
  };

  const docSpecModal =
    docSpec === null ? null : (
      <SpecDocModal
        project={project}
        spec={docSpec}
        open
        onClose={() => setDocSpec(null)}
      />
    );

  // ── 详情视图（能力页 / _domain / ADR 单文件）─────────────────────
  if (view.kind === 'page') {
    // 面包屑导航：总目录/域导航层可点（target 见 KnowledgeCrumb），当前层纯文本。
    // target 以局部变量捕获——闭包内 TS 不保留 map 主体对属性的 null 收窄。
    const crumbItems = knowledgeCrumbs(view.path).map((crumb) => {
      if (crumb.target === null) return { title: crumb.title };
      const target = crumb.target;
      return {
        title: (
          <a
            href={`#knowledge:${target}`}
            onClick={(e) => {
              e.preventDefault();
              if (target === 'index') setView({ kind: 'index' });
              else void openPage(target);
            }}
          >
            {crumb.title}
          </a>
        ),
      };
    });
    return (
      <>
        <Card variant="borderless" data-testid="knowledge-page-view">
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Breadcrumb data-testid="knowledge-page-path" items={crumbItems} />
            <Markdown remarkPlugins={[remarkGfm]} components={linkComponents}>
              {stripHtmlComments(view.content)}
            </Markdown>
          </Space>
        </Card>
        {docSpecModal}
      </>
    );
  }

  // ── 总目录视图 ────────────────────────────────────────────────────
  return (
    <>
      <Card variant="borderless" data-testid="knowledge-index-view">
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {uninitialized ? (
            <Typography.Text type="secondary" data-testid="knowledge-uninitialized">
              知识真相源尚未初始化：归档首个 SPEC 后，蒸馏管线会自动在
              spec/knowledge/ 下生成总目录与能力页。
            </Typography.Text>
          ) : (
            <>
              <div data-testid="knowledge-index-md">
                <Markdown remarkPlugins={[remarkGfm]} components={linkComponents}>
                  {stripHtmlComments(indexData?.index_md || '')}
                </Markdown>
              </div>

              {/* ADR 列表不再在此展示：adr/index.md（总目录「决策记录」节链接）
                  已含编号/状态/摘要全量清单，避免双份维护。 */}
            </>
          )}
        </Space>
      </Card>
      {docSpecModal}
    </>
  );
}
