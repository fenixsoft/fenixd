// ProjectHomeTab.tsx — 项目页「项目首页」分面（add-project-home-tab）
// 文案经 useIntl（i18n 修复轮 batch-P：本文件静态中文文案迁 i18n 目录）。
//
// 仿 GitHub 项目页形态的只读文件浏览（UI 真相源
// spec/changes/add-project-home-tab/prototype/index.html，逐区块对照）：
// 根目录最近提交条（分支 Select 移入条右端，原独立工具栏 2026-11-10 增强
// 批次取消）→ 面包屑（根=项目名）→ 文件表格（名称/大小/最近提交信息/最近
// 提交时间四列，窄屏仅名称列）→
// 文件内容盒（打开文件时，替代 README 盒位置）/ README 渲染盒（根目录）。
//
// 三卡统一 Bento 磁贴帧（project-home-tab 增强 2026-11-10，与其他页签
// 卡片风格一致；dashboard-frontend 域条款：发丝边 + 12px 圆角 + 软阴影
// + 白底，取色引主题变量随浅/深档）。内容盒按文件类型分四路渲染：markdown → react-markdown
// 安全管线（与 README 同源，MUST NOT 新写管线）；图片 → raw 通道 <img>
// 直显（不经 content 通道）；代码 → ProjectCodeBlock 高亮 + 行号；其余
// → 纯文本 pre（二进制非图片仍走降级提示）。
//
// 数据纪律：
// - active 门控：仅选中本分面发首次列表请求（对齐 QualityTab/KnowledgeTab
//   按需加载语义），未选中零请求；切离后在飞结果经 cancelled 闭包静默丢弃
//   （不报错弹窗）。
// - 进程内缓存：同 path 的列表/内容结果入 useRef Map（组件卸载即弃），
//   回分面/往返目录不重复请求。
// - 浏览位置持久化：initialPath 为 URL `?path=` 挂载初值（list.tsx 持有），
//   页内导航经 onNavigate 上行走 replace 写回；直达 path 先按目录探测，
//   404 回退父目录列表 + 条目命中为文件 → 内容视图（文件形态直达）。
// - Markdown 管线复用 react-markdown + markdownComponents 安全渲染族
//   （与 SpecDocModal 同源，SafeLink 协议白名单），MUST NOT 新写管线。
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  Alert,
  Avatar,
  Breadcrumb,
  Button,
  Empty,
  Select,
  Spin,
  Table,
} from 'antd';
import type { TableProps } from 'antd';
import { useIntl } from '@umijs/max';
import { FolderOutlined } from '@ant-design/icons';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ApiError,
  fetchProjectFileContent,
  fetchProjectFileDownloadUrl,
  fetchProjectFileList,
  fetchProjectFileRawUrl,
} from '@/services/dashboard';
import type {
  ProjectFileContentData,
  ProjectFileEntry,
  ProjectFilesListData,
} from '@/services/dashboard';
import { markdownComponents } from '@/components/markdown-shared';
import { useIsMobile } from '@/hooks/useIsMobile';
// dashboard-dark-theme 4.2：theme.ts 常量消费改引 global.less 主题 CSS 变量
// （值源 theme.ts 档位镜像：浅档与原字面值逐字节一致、深档=D2 映射；var()
// 形态使切档零 React 参与即时生效，同名局部常量保持既有消费点字面不变）。
const DSH_BG_SOFT = 'var(--fenix-bg-soft)';
const DSH_BORDER_SECONDARY = 'var(--fenix-border-secondary)';
const DSH_SPLIT = 'var(--fenix-split)';
const DSH_TEXT_SECONDARY = 'var(--fenix-text-secondary)';
const DSH_TEXT_TERTIARY = 'var(--fenix-text-tertiary)';
import {
  MONO_FONT,
  fileKind,
  formatBytes,
  formatRelativeTime,
  homeCrumbs,
  parseHomePath,
  splitHomePath,
} from './projectHomeShared';
import type { ProjectFileKind } from './projectHomeShared';
import { ProjectCodeBlock } from './ProjectCodeBlock';
import { ICON_BLUE, ProjectFileIcon } from './ProjectFileIcon';

// remarkPlugins 提为模块级常量（对齐 KnowledgeTab KNOWLEDGE_REMARK_PLUGINS
// 先例）：内联数组每次渲染新建引用会让 react-markdown 重新 parse。
const HOME_REMARK_PLUGINS = [remarkGfm];

// 内容盒类型标签查表（code-review item 8720c2e78c21：嵌套三元被审查规则
// 禁止，抽为查表局部计算，范式对齐 CodeFixProgressCard 的 barStatus/
// subTestId 局部计算先例）
const HOME_VIEW_KIND_LABEL: Record<ProjectFileKind, string> = {
  markdown: 'projects.home.kind.markdown',
  image: 'projects.home.kind.image',
  code: 'projects.home.kind.code',
  text: 'projects.home.kind.text',
};

// Bento 磁贴帧（dashboard-frontend 域条款；SpecTimeline OV_TILE 先例同值，
// 2026-11-06 定形）：发丝边 + 12px 圆角 + 软阴影 + 白底。文件列表 / 文件
// 内容 / README 三卡统一帧形态，与其他页签卡片风格一致。取色引主题 CSS
// 变量随浅/深档切换（code-review item 2a10a9923074：与同文件 DSH_* 及
// command-center CARD_FRAME_BORDER/CARD_BG 同口径；浅档 --fenix-hairline
// 即定形值 #eef2f7、--fenix-bg-elevated 即 #ffffff，暗色宿主下不再出现
// 外框纯白、内部深色代码块的割裂渲染）。
const TILE_BORDER = 'var(--fenix-hairline)';
const TILE_SHADOW =
  '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)';
const TILE_FRAME: CSSProperties = {
  border: `1px solid ${TILE_BORDER}`,
  borderRadius: 12,
  background: 'var(--fenix-bg-elevated)',
  boxShadow: TILE_SHADOW,
  overflow: 'hidden',
};

// 类型图标蓝：ICON_BLUE 从 ProjectFileIcon 导入（antd blue-6，与全站蓝色 ramp
// 同源——progressPhase TRACK 色同 ramp；DSH_PRIMARY 是近黑主色不适合图标语义）。
// 文件夹与文件图标统一蓝色系；常用扩展名由 ProjectFileIcon 渲染 simple-icons 品牌图标。

interface ProjectHomeTabProps {
  project: string;
  active: boolean;
  /** URL `?path=` 的挂载初值（list.tsx 持有持久化；仅挂载时消费一次）。 */
  initialPath: string;
  /** 浏览位置上行（list.tsx replace 写回 URL；根目录传空串）。 */
  onNavigate: (path: string) => void;
}

// Markdown 渲染体（README 盒与 *.md 文件视图共用同一安全管线形态；
// 单源组件防止两处 padding/管线漂移，管线本身仍是 markdown-shared 复用）。
function MarkdownBody({ content }: { content: string }) {
  return (
    <div style={{ padding: '20px 24px 28px', fontSize: 14, lineHeight: 1.7 }}>
      <Markdown remarkPlugins={HOME_REMARK_PLUGINS} components={markdownComponents}>
        {content}
      </Markdown>
    </div>
  );
}

// 目录列表加载错误三档归类（code-review item ec8b11395f54）：loadDir 与
// initialPath 直达回退分支共用同一口径，防止两处文案各自漂移——404 →
// 路径不存在、ApiError → 服务端消息、其余 → 加载失败。
function dirLoadErrorMessage(e: unknown, intl: ReturnType<typeof useIntl>): string {
  // 嵌套三元被审查规则禁止（同文件 8720c2e78c21 注释口径，code-review item
  // 401bd28d929d）：抽为 if/else 逐档返回，与 HOME_VIEW_KIND_LABEL 查表
  // 先例及 CodeFixProgressCard 局部计算范式对齐
  if (e instanceof ApiError && e.status === 404) {
    return intl.formatMessage({ id: 'projects.home.dirLoadNotFound' });
  }
  if (e instanceof ApiError) {
    return e.message;
  }
  return intl.formatMessage({ id: 'projects.home.dirLoadFailed' });
}

// 图片直显（raw 通道 <img>，不经 content 通道；加载失败降级提示，下载
// 按钮在内容盒头部仍可用）。调用处以 key={filePath} 挂载，切换文件即
// 重置失败态。
function FileImagePreview({ project, path }: { project: string; path: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div
        data-testid="project-home-image-fallback"
        style={{
          padding: '40px 16px',
          textAlign: 'center',
          color: DSH_TEXT_TERTIARY,
          fontSize: 13,
        }}
      >
        {intl.formatMessage({ id: 'projects.home.imgLoadFailed' })}
      </div>
    );
  }
  return (
    <div style={{ padding: 16, display: 'flex', justifyContent: 'center' }}>
      <img
        data-testid="project-home-image"
        src={fetchProjectFileRawUrl(project, path)}
        alt={path}
        style={{ maxWidth: '100%', maxHeight: 480 }}
        onError={() => setFailed(true)}
      />
    </div>
  );
}

export default function ProjectHomeTab({
  project,
  active,
  initialPath,
  onNavigate,
}: ProjectHomeTabProps) {
  const intl = useIntl();
  const isMobile = useIsMobile();

  // 当前目录（仓库根相对路径，'' = 根）与打开的文件（当前目录下文件名）
  const [dir, setDir] = useState('');
  const [file, setFile] = useState<string | null>(null);
  const [dirData, setDirData] = useState<ProjectFilesListData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fileData, setFileData] = useState<ProjectFileContentData | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState('');
  const [readmeData, setReadmeData] = useState<ProjectFileContentData | null>(null);

  // 进程内缓存（组件卸载即弃，useRef 随实例生命周期）：列表按目录 path、
  // 内容按文件 path（README 以文件名同键复用内容缓存）
  const listCacheRef = useRef<Map<string, ProjectFilesListData>>(new Map());
  const contentCacheRef = useRef<Map<string, ProjectFileContentData>>(new Map());

  // 跨项目切换清态（code-review item 9b27c5dad1f5）：本组件随 Tab 常驻挂载
  // （list.tsx 挂载无 key={name}，refs 不随项目切换重建，project 变化只重启
  // 加载 effect、不卸载组件，口径同 KnowledgeTab setView 复位 /
  // ArchitectureTab setStatus(null) / CodeFixProgressCard setProgress(null)），
  // dir/file/dirData/fileData/fileError/error/readmeData 会保留上一项目的
  // 浏览位置与数据——面包屑与文件表格先按旧位置渲染（新项目同路径 404 时
  // 误报「路径不存在」，恰好存在同路径则静默串显），README 盒按旧
  // dirData.readme 渲染直至新数据到达。loading/fileLoading 一并复位：在飞
  // 请求被 cancelled 丢弃后不会回调 setXxxLoading(false)（口径同 openDir 的
  // 注释）。两个进程内缓存以纯 path 为键、不含 project 维度（code-review
  // item c6bb6045054b）：切项目不清空会同路径命中旧项目的列表/内容/README
  // 数据串显（所见为 A 的内容、下载按钮所指却是 B），故清态时同步清空两 Map
  // ——与本 effect 同口径、二选一关系的另一形态见 SpecDocModal 缓存键含
  // project 维度。声明序在各加载 effect 之前：project 变化时清空先于新请求
  // 响应执行，不会误清新项目刚取到的数据。
  useEffect(() => {
    setDir('');
    setFile(null);
    setDirData(null);
    setFileData(null);
    setFileError('');
    setError('');
    setReadmeData(null);
    setLoading(false);
    setFileLoading(false);
    listCacheRef.current.clear();
    contentCacheRef.current.clear();
  }, [project]);

  // initialPath 直达解析只做一次（挂载初值快照）：空串视为无 seed（常规根
  // 目录加载）；非空在首次激活时先按目录探测、404 回退父目录 + 文件命中
  const seedRef = useRef<string | null>(parseHomePath(initialPath) || null);

  const filePath = file === null ? null : dir ? `${dir}/${file}` : file;

  // ── 目录列表加载（active + dir 双门控；缓存命中免请求）──────────────
  // active=false 时零请求；切离分面触发本 effect cleanup（cancelled=true），
  // 在飞响应落地前被静默丢弃。
  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const loadDir = async (target: string) => {
      setError('');
      setLoading(true);
      const cached = listCacheRef.current.get(target);
      if (cached) {
        setDirData(cached);
        setLoading(false);
        return;
      }
      try {
        const d = await fetchProjectFileList(project, target);
        if (cancelled) return;
        listCacheRef.current.set(target, d);
        setDirData(d);
      } catch (e) {
        if (cancelled) return;
        setError(dirLoadErrorMessage(e, intl));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    // 首次激活的直达解析：非空 seed 先按目录探测，list 404（文件路径不经
    // 列表通道）回退父目录列表 + 条目命中为文件 → 内容视图。父目录列表先
    // 入缓存，随后的常规 effect 轮从缓存命中免重拉；文件内容仅在 404 定性
    // 探测成功时先入缓存，列表命中形态交由内容加载 effect 拉取（见下文
    // code-review item 05c49e2d3251 注记）。
    const seed = seedRef.current;
    seedRef.current = null;
    if (seed !== null) {
      setLoading(true);
      void (async () => {
        try {
          const d = await fetchProjectFileList(project, seed);
          if (cancelled) return;
          listCacheRef.current.set(seed, d);
          setDir(seed);
          return;
        } catch {
          /* 非目录 → 文件形态回退探测 */
        }
        if (cancelled) return;
        const { dir: parent, name } = splitHomePath(seed);
        try {
          const pd = await fetchProjectFileList(project, parent);
          if (cancelled) return;
          listCacheRef.current.set(parent, pd);
          setDir(parent);
          const inList = pd.entries.some((en) => en.name === name && !en.dir);
          if (inList || pd.truncated_count) {
            // 列表超 200 项截断（truncated_count 非空）时 entries 不含截断外
            // 条目，未命中不代表不存在（code-review item f4dcabe6b80c）：经
            // content 通道对 seed 探测一次定性（404 才判路径不存在），探测
            // 成功响应兼作文件内容入缓存免二次请求；非截断目录未命中即真
            // 不存在，维持原判定。图片形态不探测（code-review item
            // e59f75c277b5）：直显走 raw 通道，content 探测响应注定被丢弃，
            // 白打一次请求——直接开视图，由 <img> 的失败降级兜底呈现。
            let probed: ProjectFileContentData | null = null;
            if (!inList && fileKind(seed) !== 'image') {
              try {
                probed = await fetchProjectFileContent(project, seed);
              } catch (pe) {
                if (cancelled) return;
                if (pe instanceof ApiError && pe.status === 404) {
                  setError(intl.formatMessage({ id: 'projects.home.pathMissing' }));
                } else {
                  // 非 404（服务/网络故障）无法定性存在性：仍开文件视图，
                  // 由内容加载 effect 按既有 fileError 口径重试呈现结果，
                  // 不走 error 通道顶掉父目录列表渲染
                  setFile(name);
                }
                return;
              }
              if (cancelled) return;
            }
            setFile(name);
            // 图片文件不经 content 通道（直显走 raw <img>），免无意义请求。
            // 列表命中（probed 为 null）时不再在此自行拉取内容：setFile 先行
            // 已触发内容加载 effect 以空缓存发请求，此处再 await 同一文件即
            // 并发重复请求，且 setDir 触发的主 effect 重跑已置 cancelled、该
            // 响应注定被丢弃（code-review item 05c49e2d3251）——内容拉取统一
            // 交由内容加载 effect 按既有 fileError 口径承担；此处仅把 404
            // 定性探测的成功响应入缓存免二次请求。
            if (fileKind(seed) !== 'image' && probed) {
              contentCacheRef.current.set(seed, probed);
            }
          } else {
            setError(intl.formatMessage({ id: 'projects.home.pathMissing' }));
          }
        } catch (e) {
          // 回退分支父目录列表失败与 loadDir 同口径三档归类（code-review
          // item ec8b11395f54）：不再无差别误报「路径不存在」误导排查方向。
          if (!cancelled) setError(dirLoadErrorMessage(e, intl));
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
      return () => {
        cancelled = true;
      };
    }

    void loadDir(dir);
    return () => {
      cancelled = true;
    };
  }, [active, dir, project]);

  // ── 文件内容加载（打开文件时；缓存命中免请求）───────────────────────
  useEffect(() => {
    if (filePath === null || !active) return;
    // 图片直显走 raw 通道（<img> 加载完整字节），不经 content 通道——
    // 免一次无意义请求，也避开 256 KiB 截断语义（raw 无截断）
    if (fileKind(filePath) === 'image') return;
    const cached = contentCacheRef.current.get(filePath);
    if (cached) {
      setFileData(cached);
      return;
    }
    let cancelled = false;
    setFileError('');
    setFileLoading(true);
    fetchProjectFileContent(project, filePath)
      .then((c) => {
        if (cancelled) return;
        contentCacheRef.current.set(filePath, c);
        setFileData(c);
      })
      .catch((e) => {
        if (cancelled) return;
        setFileError(e instanceof ApiError ? e.message : intl.formatMessage({ id: 'projects.home.fileLoadFailed' }));
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filePath, active, project]);

  // ── README 加载（根目录且未打开文件时按 readme 字段拉内容通道）───────
  // 拉取失败静默降级为不渲染 README 盒（无 README 项目不渲染空盒的边界延伸）。
  const readmeName = dir === '' && file === null ? dirData?.readme ?? null : null;
  useEffect(() => {
    if (!readmeName || !active) return;
    const cached = contentCacheRef.current.get(readmeName);
    if (cached) {
      setReadmeData(cached);
      return;
    }
    let cancelled = false;
    setReadmeData(null);
    fetchProjectFileContent(project, readmeName)
      .then((c) => {
        if (cancelled) return;
        contentCacheRef.current.set(readmeName, c);
        setReadmeData(c);
      })
      .catch(() => {
        if (!cancelled) setReadmeData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [readmeName, active, project]);

  // ── 导航动作（原地更新列表，不整页刷新、不改路由路径）───────────────
  // fileLoading 一并复位：图片文件的内容 effect 在取数前短路返回，在飞
  // 文本请求被 cancel 后不会回调 setFileLoading(false)，不复位会永久 Spin。
  const openDir = (name: string) => {
    const next = dir ? `${dir}/${name}` : name;
    setFile(null);
    setFileData(null);
    setFileError('');
    setFileLoading(false);
    setDir(next);
    onNavigate(next);
  };
  const openFile = (name: string) => {
    setFile(name);
    setFileData(null);
    setFileError('');
    setFileLoading(false);
    onNavigate(dir ? `${dir}/${name}` : name);
  };
  /** 面包屑回退：depth=0 回根目录，n 回前 n 段目录。 */
  const goDepth = (depth: number) => {
    const next = homeCrumbs(dir).slice(0, depth).join('/');
    setFile(null);
    setFileData(null);
    setFileError('');
    setFileLoading(false);
    setDir(next);
    onNavigate(next);
  };

  // ── 文件表格（四列；窄屏 <768px 仅名称列）──────────────────────────
  const columns: TableProps<ProjectFileEntry>['columns'] = [
    {
      title: intl.formatMessage({ id: 'projects.home.col.name' }),
      dataIndex: 'name',
      key: 'name',
      ellipsis: false,
      render: (_v, r) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {r.dir ? (
            <FolderOutlined
              style={{ color: r.hidden ? DSH_TEXT_TERTIARY : ICON_BLUE, flex: 'none' }}
            />
          ) : (
            <ProjectFileIcon name={r.name} muted={r.hidden === true} />
          )}
          <span style={{ fontSize: 14, color: r.hidden ? DSH_TEXT_TERTIARY : undefined }}>
            {r.name}
          </span>
        </span>
      ),
    },
    {
      // 大小列（2026-11-10 增强批次）：文件 stat 实际大小（后端 bytes 字段，
      // formatBytes 自动 B/KB/MB/GB 档位）；目录不做递归汇总，显示「目录」。
      // 左对齐（2026-11-11 用户修正：与其他列头同向，扫读更顺）。
      title: intl.formatMessage({ id: 'projects.home.colSize' }),
      dataIndex: 'bytes',
      key: 'size',
      width: 96,
      hidden: isMobile,
      render: (v: number | null, r) => (
        <span
          style={{
            display: 'block',
            textAlign: 'left',
            color: r.dir || r.hidden ? DSH_TEXT_TERTIARY : DSH_TEXT_SECONDARY,
            fontSize: 13,
            whiteSpace: 'nowrap',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {r.dir ? intl.formatMessage({ id: 'projects.home.dirEntry' }) : v !== null && v !== undefined ? formatBytes(v) : '—'}
        </span>
      ),
    },
    {
      title: intl.formatMessage({ id: 'projects.home.colLastCommitMsg' }),
      dataIndex: ['last_commit', 'message'],
      key: 'msg',
      ellipsis: true,
      hidden: isMobile,
      render: (v: string | undefined, r) => (
        <span
          style={{
            color: r.hidden ? DSH_TEXT_TERTIARY : DSH_TEXT_SECONDARY,
            fontSize: 13,
          }}
        >
          {v || '—'}
        </span>
      ),
    },
    {
      title: intl.formatMessage({ id: 'projects.home.colLastCommitTime' }),
      dataIndex: ['last_commit', 'time'],
      key: 'time',
      hidden: isMobile,
      width: 128,
      render: (v: string | undefined, r) => (
        <span
          style={{
            display: 'block',
            textAlign: 'right',
            color: DSH_TEXT_TERTIARY,
            fontSize: 13,
            whiteSpace: 'nowrap',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {/* hidden 行同样显示时间（code-review item 6ac97d811eb5）：与信息列/
              大小列同口径，不因 hidden 截断——灰显语义由行内颜色承载 */}
          {v ? intl.formatMessage(formatRelativeTime(v)) : '—'}
        </span>
      ),
    },
  ];

  const crumbs = homeCrumbs(dir);
  const atRoot = dir === '' && file === null;
  const latest = atRoot ? dirData?.latest ?? null : null;
  // 作者空值口径对齐（code-review item 3da4b1325ad3）：头像首字与姓名位
  // 共用同一回退值，author 缺失/为空时不再出现头像「?」而姓名空白的分叉。
  const latestAuthor = latest?.author || intl.formatMessage({ id: 'projects.home.authorFallback' });
  const nonGit = dirData?.non_git === true;
  // 内容盒渲染分类（project-home-tab 增强：md/图片/代码/纯文本四路）
  const viewKind = filePath !== null ? fileKind(filePath) : null;
  // 类型标签（code-review item 8720c2e78c21：嵌套三元被审查规则禁止，抽为
  // 查表局部计算，见 HOME_VIEW_KIND_LABEL）
  const kindLabel = viewKind !== null ? intl.formatMessage({ id: HOME_VIEW_KIND_LABEL[viewKind] }) : null;

  if (nonGit) {
    // 非 git 项目空态：Empty + 中文说明，不报错弹窗、不渲染破损列表
    return (
      <Empty
        data-testid="project-home-empty"
        description={intl.formatMessage({ id: 'projects.home.noGitHistory' })}
        style={{ padding: '56px 0' }}
      />
    );
  }

  return (
    <div data-testid="project-home-panel">
      <div
        data-testid="project-home-filetable"
        style={TILE_FRAME}
      >
        {/* 根目录最近提交条（作者 / 短 hash / 相对时间；打开文件时不渲染）。
            分支 Select 从原独立工具栏移入本条右侧（2026-11-10 增强批次：
            去标头减面积；单值只读不提供切换，原型中分支/标签为假数据演示，
            不落实现） */}
        {latest && (
          <div
            data-testid="project-home-latest-commit"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
            }}
          >
            <Avatar
              size={24}
              style={{
                backgroundColor: DSH_BG_SOFT,
                color: DSH_TEXT_SECONDARY,
                border: `1px solid ${DSH_BORDER_SECONDARY}`,
                fontSize: 12,
                flex: 'none',
              }}
            >
              {latestAuthor.slice(0, 1)}
            </Avatar>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{latestAuthor}</span>
            <span
              style={{
                fontFamily: MONO_FONT,
                fontSize: 12,
                color: DSH_TEXT_SECONDARY,
                background: DSH_BG_SOFT,
                border: `1px solid ${DSH_BORDER_SECONDARY}`,
                borderRadius: 4,
                padding: '1px 6px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {latest.hash}
            </span>
            <span
              style={{
                marginLeft: 'auto',
                color: DSH_TEXT_TERTIARY,
                fontSize: 12,
                whiteSpace: 'nowrap',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {intl.formatMessage(formatRelativeTime(latest.time))}
            </span>
            {dirData?.branch && (
              <Select
                size="small"
                style={{ width: 150 }}
                value={dirData.branch}
                options={[{ value: dirData.branch, label: dirData.branch }]}
              />
            )}
          </div>
        )}

        {/* 面包屑（进入目录后才显示；根目录整条隐藏——2026-11-10 第三批增强）。
            可点击段补 href={'#'} 保住键盘可达（Tab 聚焦/回车触发，preventDefault
            仍拦跳转；code-review item d63a1ac281e2，与 KnowledgeTab 面包屑
            锚点口径对齐）。 */}
        {dir !== '' && (
          <div
            data-testid="project-home-breadcrumb"
            style={{
              padding: '8px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
              fontSize: 14,
            }}
          >
            {/* dir!=='' 门控下 homeCrumbs(dir) 恒 >= 1 段（dir 各赋值点均归一化
                非空），根目录形态由外层整条隐藏承载，无空段回退分支
                （code-review item cc77072976ac）。 */}
            <Breadcrumb
              items={[
                {
                  title: (
                    <a
                      href={'#'}
                      onClick={(e) => {
                        e.preventDefault();
                        goDepth(0);
                      }}
                    >
                      {project}
                    </a>
                  ),
                },
                ...crumbs.map((seg, i) => ({
                  title:
                    i === crumbs.length - 1 && file === null ? (
                      <span style={{ fontWeight: 600 }}>{seg}</span>
                    ) : (
                      <a
                        href={'#'}
                        onClick={(e) => {
                          e.preventDefault();
                          goDepth(i + 1);
                        }}
                      >
                        {seg}
                      </a>
                    ),
                })),
                ...(file ? [{ title: <span style={{ fontWeight: 600 }}>{file}</span> }] : []),
              ]}
            />
          </div>
        )}

        {error ? (
          <Alert type="warning" showIcon message={error} style={{ margin: '12px 16px' }} />
        ) : (
          <Table<ProjectFileEntry>
            size="middle"
            loading={loading}
            pagination={false}
            columns={columns}
            dataSource={(dirData?.entries ?? []).map((e) => ({ ...e, key: e.name }))}
            onRow={(r) => ({
              onClick: () => (r.dir ? openDir(r.name) : openFile(r.name)),
              style: { cursor: 'pointer' },
            })}
          />
        )}

        {/* 目录条目截断提示（超 200 项；spec「如『仅展示前 200 项』」） */}
        {!!dirData?.truncated_count && (
          <div
            style={{
              padding: '8px 16px',
              borderTop: `1px solid ${DSH_SPLIT}`,
              background: DSH_BG_SOFT,
              color: DSH_TEXT_SECONDARY,
              fontSize: 12,
            }}
          >
            {intl.formatMessage({ id: 'projects.home.dirTruncated' }, { count: dirData.truncated_count })}
          </div>
        )}
      </div>

      {/* 文件内容盒（打开文件时替代 README 盒位置） */}
      {filePath !== null && (
        <div
          data-testid="project-home-fileview"
          style={{ ...TILE_FRAME, marginTop: 16 }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
              background: DSH_BG_SOFT,
              flexWrap: 'wrap',
            }}
          >
            <ProjectFileIcon name={file ?? ''} />
            <span style={{ fontSize: 14, fontWeight: 600 }}>{file}</span>
            {viewKind !== null && (
              <span
                style={{
                  fontSize: 12,
                  padding: '1px 8px',
                  borderRadius: 10,
                  background: DSH_BG_SOFT,
                  border: `1px solid ${DSH_SPLIT}`,
                  color: DSH_TEXT_SECONDARY,
                }}
              >
                {kindLabel}
              </span>
            )}
            {fileData && !fileData.binary && (
              <span
                style={{
                  fontSize: 12,
                  color: DSH_TEXT_TERTIARY,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {intl.formatMessage({ id: 'projects.home.linesAndSize' }, { lines: fileData.lines, size: formatBytes(fileData.bytes) })}
              </span>
            )}
            <span style={{ marginLeft: 'auto' }}>
              <Button size="small" href={fetchProjectFileDownloadUrl(project, filePath)} download>
                {intl.formatMessage({ id: 'projects.home.download' })}
              </Button>
            </span>
          </div>
          {fileError ? (
            <Alert type="warning" showIcon message={fileError} style={{ margin: 16 }} />
          ) : fileLoading ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Spin />
            </div>
          ) : viewKind === 'image' ? (
            // 图片直显（raw 通道；不取 content——<img> 加载完整字节）
            <FileImagePreview key={filePath} project={project} path={filePath} />
          ) : fileData?.binary ? (
            <div
              style={{
                padding: '40px 16px',
                textAlign: 'center',
                color: DSH_TEXT_TERTIARY,
                fontSize: 13,
              }}
            >
              {intl.formatMessage({ id: 'projects.home.binaryPreviewUnsupported' })}
            </div>
          ) : fileData ? (
            <>
              {viewKind === 'markdown' ? (
                // *.md 经安全管线渲染（与 README 同源，MUST NOT 新写管线）
                <MarkdownBody content={fileData.content ?? ''} />
              ) : viewKind === 'code' ? (
                <div style={{ overflow: 'auto' }}>
                  <ProjectCodeBlock path={filePath} content={fileData.content ?? ''} />
                </div>
              ) : (
                // 非代码/非图片/非 markdown 兜底：纯文本（原形态）
                <div style={{ padding: '12px 16px', overflow: 'auto' }}>
                  <pre
                    style={{
                      margin: 0,
                      fontFamily: MONO_FONT,
                      fontSize: 13,
                      lineHeight: 1.6,
                      whiteSpace: 'pre',
                    }}
                  >
                    {fileData.content}
                  </pre>
                </div>
              )}
              {fileData.truncated && (
                <div
                  style={{
                    padding: '8px 16px',
                    borderTop: `1px solid ${DSH_SPLIT}`,
                    background: DSH_BG_SOFT,
                    color: DSH_TEXT_SECONDARY,
                    fontSize: 12,
                  }}
                >
                  {intl.formatMessage({ id: 'projects.home.fileTooLarge' })}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* README 渲染盒（根目录且未打开文件时；react-markdown 安全管线复用） */}
      {atRoot && readmeData && !readmeData.binary && dirData?.readme && (
        <div
          data-testid="project-home-readme"
          style={{ ...TILE_FRAME, marginTop: 16 }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              borderBottom: `1px solid ${DSH_SPLIT}`,
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            <ProjectFileIcon name={dirData.readme} />
            {dirData.readme}
            <span
              style={{
                marginLeft: 'auto',
                fontWeight: 400,
                color: DSH_TEXT_TERTIARY,
                fontSize: 12,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {formatBytes(readmeData.bytes)}
            </span>
          </div>
          <MarkdownBody content={readmeData.content ?? ''} />
          {readmeData.truncated && (
            <div
              style={{
                padding: '8px 16px',
                borderTop: `1px solid ${DSH_SPLIT}`,
                background: DSH_BG_SOFT,
                color: DSH_TEXT_SECONDARY,
                fontSize: 12,
              }}
            >
              {intl.formatMessage({ id: 'projects.home.fileTooLarge' })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
