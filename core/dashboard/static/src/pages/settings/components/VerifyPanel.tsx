import { Alert, Button, Card, Form, Input, Radio, Space, Switch, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

// 产物路径逐项前端校验（与后端 validate_build_artifact_paths 同口径，仅为即时报错；
// 写入权威仍在后端，非法项在 POST /api/config 被 400 拒绝）。
function artifactPathRule(rules: unknown, value: unknown): Promise<void> {
  const v = typeof value === 'string' ? value.trim() : '';
  if (!v) return Promise.reject(new Error('路径不能为空'));
  if (v.startsWith('/')) return Promise.reject(new Error('不能是绝对路径'));
  // 与后端 normalize_artifact_patterns 同口径：`".." in item.split("/")`，按
  // 独立路径段判定（docstring「含 '..' 段的项丢弃」）——dist..old/ 这类含
  // '..' 子串的合法目录名放行，与后端一致。旧注释误称后端为 `".." in item`
  // 子串判定（code-review item c30b8b2c0662），曾使前端比后端更严。
  if (v.split('/').includes('..')) return Promise.reject(new Error("不能含 '..' 路径段"));
  if (!v.includes('*') && !v.endsWith('/'))
    return Promise.reject(new Error("目录前缀须以 '/' 结尾，或使用含 '*' 的通配"));
  return Promise.resolve();
}

/** 产物三态提示文案（code-review item ca92db5ea623：抽出嵌套三元为具名函数）。 */
function buildArtifactsHint(state: HasBuildArtifactsState | undefined): string {
  if (state === 'unset' || state === undefined) {
    return '尚未配置：判定恒假（不豁免任何路径），merge-back 会写信号呼叫系统自动起草。';
  }
  if (state === 'true') {
    return '有派生物：下方列出的路径会被 merge-back 当作可丢弃的生成物处理（对齐 HEAD、不进 stash）。注意：把源码目录（如 src/）也列进来会连带取消「源码变更后重建产物」的触发。';
  }
  return '无派生物：不豁免任何路径，所有 tracked 改动都按人手维护的源码处理——这对构建输出未入库的项目是正确取值。';
}

/** has_build_artifacts 三态表单值：'unset'（未裁决）/ 'true'（有产物）/ 'false'（无产物）。
    antd Switch 无 indeterminate 语义，故用 Radio.Group 三选一承载（spec 6.3 约定）。 */
export type HasBuildArtifactsState = 'unset' | 'true' | 'false';

function toFormState(v: boolean | null | undefined): HasBuildArtifactsState {
  // 参数类型放宽含 null（code-review item deed1f27d507）：后端未裁决发 null。
  if (v === true) return 'true';
  if (v === false) return 'false';
  return 'unset';
}

interface VerifyPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮，且产物路径可编辑 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function VerifyPanel({ config, onSave, project, onConfigSynced }: VerifyPanelProps) {
  const [form] = Form.useForm();
  // 保存重入守卫（code-review item 2a3a76864687）：onSave 是异步，提交期间
  // 按钮可继续点击会发出重叠保存请求（并发写同一配置文件，结果取决于响应
  // 到达顺序）——saving 期间置 loading/disabled 并在入口短路。
  const [saving, setSaving] = useState(false);
  // 产物路径为项目级键：用户级作用域下只读展示（无 project 即用户级）
  const artifactEditable = Boolean(project);
  // 三态联动：无产物（false）时路径列表隐藏并显示结案提示
  const hasBuildArtifacts = Form.useWatch('has_build_artifacts', form) as
    | HasBuildArtifactsState
    | undefined;

  useEffect(() => {
    form.setFieldsValue({
      static_scope: config.verify?.static_scope || 'main',
      deps_mode: config.verify?.deps_mode || 'hardlink',
      serving_reclaim_enabled: config.verify?.serving_reclaim?.enabled ?? true,
      build_artifact_paths: (config.worktree?.build_artifact_paths || []).map(
        (p) => ({ path: p }),
      ),
      has_build_artifacts: toFormState(config.worktree?.has_build_artifacts),
    });
  }, [config.verify, config.worktree, form]);

  // 「无派生物」时清空路径 List 的 store 值（code-review item aceafc981274）：
  // 三态切到 false 时整个 Form.List（name='build_artifact_paths'）卸载，
  // rc-field-form 默认保留卸载项值且 validateFields 只校验在场字段——此前
  // 输入的任意行（含 artifactPathRule 校验失败行，如 dist 缺尾斜杠）残留在
  // form store 被 handleSave 原样提交。切到「无派生物」即显式清值，保证
  // 提交口径与所见一致；再切回「有派生物」时从空列表开始，不受残留行污染。
  useEffect(() => {
    if (hasBuildArtifacts === 'false') {
      form.setFieldValue('build_artifact_paths', []);
    }
  }, [hasBuildArtifacts, form]);

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    try {
      const values = await form.validateFields();
      const payload: Partial<ConfigData> = {
        verify: {
          static_scope: values.static_scope,
          deps_mode: values.deps_mode,
          serving_reclaim: { enabled: values.serving_reclaim_enabled },
        },
      };
      // 产物路径仅项目级可写（用户级作用域下该卡片只读，不提交该键）
      if (artifactEditable) {
        // 校验器已拒绝空路径（artifactPathRule 的「路径不能为空」），故此处
        // 无需 filter 剔除空行——旧 filter 恒不生效（code-review item
        // 721019da2aa9）。保留 trim 归一（前后空白不影响规则判定）。
        payload.worktree = {
          build_artifact_paths: (values.build_artifact_paths || []).map(
            (row: { path?: string }) => (row?.path || '').trim(),
          ),
        };
        // 三态 → 配置值（code-review item 22ec00069cd7）：'unset' 表示撤销裁决，
        // 若省略该键，后端 _merge_config 会保留旧布尔值，保存+刷新后单选框弹回
        // 有/无产物、用户无法真正回到未配置态。null = 显式清除该键后由后端按未
        // 裁决处理（未被配置时读取为 undefined）。
        if (values.has_build_artifacts === 'true') {
          payload.worktree.has_build_artifacts = true;
        } else if (values.has_build_artifacts === 'false') {
          payload.worktree.has_build_artifacts = false;
        } else {
          // unset：显式清除（null 语义由 write 路径处理为移除该键）。
          // ConfigData['worktree'].has_build_artifacts 已声明 boolean | null
          // （code-review item b7d40351517d）：直接赋 null，「有意写 null」
          // 由类型系统表达，不再用断言掩盖（断言会静默挫败未来收紧）。
          payload.worktree.has_build_artifacts = null;
        }
      }
      await onSave(payload);
    } catch (error) {
      console.error('Validation failed:', error);
    } finally {
      setSaving(false);
    }
  };

  const artifactsState = hasBuildArtifacts ?? toFormState(config.worktree?.has_build_artifacts);
  const declaredNoArtifacts = artifactsState === 'false';

  return (
    <div>
      <h3>验证契约</h3>
      <Text type="secondary">
        静态验证契约（.fenix/verify.yaml）的被测实例服务范围。两种范围都会在
        每轮验证前执行契约的 prepare 构建步骤，并把验证场景 URL 全量改写到本次启动的实例。
      </Text>
      {/* 单一 Form 承载两张卡片：产物路径卡片的 Form.List 必须处于 Form 上下文内，
          否则 add/remove 会落到 rc-field-form 的默认空上下文（warning 桩），
          点击「添加产物路径」静默无反应。 */}
      <Form form={form} layout="vertical">
        <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="static_scope"
            label={
              <>
                验证实例范围<span className="label-note">（verify.static_scope）</span>
              </>
            }
            rules={[{ required: true, message: '请选择服务范围' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="main">
                  <strong>main</strong> — 在 main 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在主树构建并启动被测实例。实现合并进主树后产物必然新鲜，
                      与现有运行实例共享，资源占用最小。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="worktree">
                  <strong>worktree</strong> — 在 worktree 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在专用 serving worktree 内构建并启动服务，与主树运行实例
                      完全隔离（验证流量不影响主实例）。每次 HEAD 变化自动重建
                      worktree 与产物。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="deps_mode"
            label={
              <>
                依赖供给模式<span className="label-note">（verify.deps_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择依赖供给模式' }]}
            extra="设置 worktree 中 node_modules 的引用方式，仅使用 node.js 的项目需要设置此选项"
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="prefer-offline">
                  <strong>prefer-offline</strong> — npm 缓存安装
                  <div>
                    <Text type="secondary">
                      在 worktree 内 npm ci --prefer-offline（锁文件严格安装、
                      走用户级 npm 缓存），失败回退 npm install。无共享 inode，
                      最安全；首次安装约数十秒。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="hardlink">
                  <strong>hardlink</strong> — 主树硬链接副本（默认）
                  <div>
                    <Text type="secondary">
                      秒级完成、共享 inode 不占双倍空间。npm 更新包 = 重新解包
                      （新 inode），主树不受影响；但构建缓存等 in-place 写入会
                      穿透共享 inode——避免主树与 worktree 并发构建。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row），
              开关控件不带「开/关」文字（与其余开关统一） */}
          <div className="switch-inline-row">
            <Form.Item name="serving_reclaim_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="serving-reclaim-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              serving 目录自动回收
              <span className="label-note">（verify.serving_reclaim.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            daemon 启动时与周期清扫对 .fenix/verify-serving/ 下无主 worktree（spec 不在
            changes/archive、未登记、无活进程、超宽限期）执行 git worktree remove --force +
            prune，并按同判据回收 &lt;spec&gt;-boot.log。关闭后不再自动回收（存量目录需人工清理）。
          </Text>
          {/* 收尾代码质量审查已迁至独立「质量」页签（add-quality-tab）：
              键路径 verify.impl_code_review 不变，仅换呈现位置 */}
        </Card>

        {/* 构建产物路径：标题与说明置于卡片外，与上方「验证契约」节同构 */}
        <h3 style={{ marginTop: 32 }}>构建产物路径</h3>
        <Text type="secondary">
          这是一份豁免清单，告诉 merge-back 哪些路径是「由源码生成的派生物」、
          不必当作需要人工处理的改动。产物改动会被对齐 HEAD、不进入 WIP 重叠 stash，
          避免 pop 冲突与误报告警。支持目录前缀（如 dist/，须以 / 结尾）与文件通配
          （如 release-*.zip，含 *）。它不影响构建、也不影响验证，是否/何时构建由构建配置
          不由本设置逻辑决定。
        </Text>
        <Card style={{ marginTop: 12 }} data-testid="artifact-paths-card">
          {artifactEditable ? (
            <>
              <Form.Item
                name="has_build_artifacts"
                label={
                  <>
                    需要豁免的派生产物
                    <span className="label-note">（worktree.has_build_artifacts）</span>
                  </>
                }
                extra={buildArtifactsHint(hasBuildArtifacts)}
                data-testid="has-build-artifacts-form-item"
              >
                <Radio.Group data-testid="has-build-artifacts-radio">
                  <Radio value="unset">未配置</Radio>
                  <Radio value="true">有派生物</Radio>
                  <Radio value="false">无派生物</Radio>
                </Radio.Group>
              </Form.Item>
              {declaredNoArtifacts ? (
                <Alert
                  type="success"
                  showIcon
                  message="已声明：本项目无需要豁免的派生产物"
                  description="git 跟踪范围内全部是人手维护的内容（构建输出如 dist/ 未入库）。merge-back 无需区分产物与语义，所有改动都按源码处理。此声明不影响构建与验证。"
                  data-testid="artifact-paths-no-artifacts-alert"
                />
              ) : (
                <Form.List name="build_artifact_paths">
                  {(fields, { add, remove }) => (
                    // 组容器保留共享 id 供批量查询；行内 Input 的 testid 带行
                    // 索引（code-review item 2c30d035c56b）——旧实现各行复用
                    // 同一 testid，测试只能 getAllByTestId+index 整体寻址，
                    // 无法可靠定位/重排特定行。
                    <div data-testid="artifact-path-inputs">
                      {fields.map((field) => (
                        <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                          <Form.Item
                            name={[field.name, 'path']}
                            rules={[{ validator: artifactPathRule }]}
                            style={{ marginBottom: 0, minWidth: 280 }}
                          >
                            <Input
                              placeholder="例如 dist/ 或 release-*.zip"
                              data-testid={`artifact-path-input-${field.name}`}
                            />
                          </Form.Item>
                          <Button
                            type="text"
                            danger
                            icon={<MinusCircleOutlined />}
                            aria-label="删除此行"
                            onClick={() => remove(field.name)}
                          />
                        </Space>
                      ))}
                      <Button
                        type="dashed"
                        icon={<PlusOutlined />}
                        onClick={() => add({ path: '' })}
                        data-testid="artifact-path-add"
                      >
                        添加产物路径
                      </Button>
                    </div>
                  )}
                </Form.List>
              )}
            </>
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                message="构建产物路径为项目级设置，用户级作用域下不可编辑。请在页面右上角把「作用域」切换到对应项目后添加或修改。"
                data-testid="artifact-paths-scope-hint"
              />
              <div style={{ marginTop: 12 }}>
                <Text>
                  需要豁免的派生产物：{' '}
                  {/* 后端 worktree_config_view 恒发该键、未裁决时取 None → JSON
                      `null`（**不是 undefined**）。旧实现只比 `=== undefined`，在
                      user-scope 只读分支下三支全假，该行渲染成空标签
                      （code-review item deed1f27d507）。以 null 为未裁决判据。 */}
                  {(config.worktree?.has_build_artifacts === null ||
                    config.worktree?.has_build_artifacts === undefined) && (
                    <Text type="warning">未配置（未裁决，判定恒假，等待自动起草）</Text>
                  )}
                  {config.worktree?.has_build_artifacts === true && <Text>有派生物</Text>}
                  {config.worktree?.has_build_artifacts === false && (
                    <Text>无派生物（已声明，不影响构建与验证）</Text>
                  )}
                </Text>
              </div>
              {config.worktree?.build_artifact_paths?.length ? (
                <ul style={{ margin: '12px 0 0', paddingLeft: 20 }}>
                  {config.worktree.build_artifact_paths.map((p, i) => {
                    // code-review item c5b0bd57f3db：稳定 key——配置路径实际唯一，
                    // 直接用路径本身；病态重复条目回退「路径-索引」防 React 撞
                    // key。索引 key 会在重排/插入/删除时按位置复用错误 DOM 节点。
                    // 可选链：map 回调内 TS 收窄失效，外层守卫已保证非空。
                    const key =
                      config.worktree?.build_artifact_paths?.indexOf(p) === i ? p : `${p}-${i}`;
                    return (
                      <li key={key}>
                        <code>{p}</code>
                      </li>
                    );
                  })}
                </ul>
              ) : config.worktree?.has_build_artifacts === true ? (
                // true + 空路径 = 三态表的「标志与路径不一致」未决态
                //（is_artifact_config_unresolved：判定恒假、按无产物处理）。
                // 旧实现此组合静默渲染「有派生物」、无路径亦无说明（code-review
                // item def8b9836b7e，下方 !==true 守卫把未决提示一并抑制）——
                // 显式说明矛盾态与其保守侧生效语义。
                <Text type="warning" style={{ display: 'block', marginTop: 12 }}>
                  已声明「有派生物」但豁免路径列表为空（标志与路径不一致，按未裁决处理）：
                  产物判定恒假、merge-back 全部按源码改动对待。请切到项目级作用域补全
                  路径，或把声明改为「无派生物」。
                </Text>
              ) : (
                config.worktree?.has_build_artifacts !== false &&
                config.worktree?.has_build_artifacts !== true && (
                  <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
                    未配置豁免路径（未裁决，等待系统自动起草）
                  </Text>
                )
              )}
            </>
          )}
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="verify" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="verify-save">
          保存
        </Button>
      </div>
    </div>
  );
}
