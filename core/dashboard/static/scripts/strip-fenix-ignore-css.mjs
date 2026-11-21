// tailwind.gen.css 生成侧后处理：剥除源码注释 [fenix-ignore:<id>] 标注被
// tailwind content 扫描吸入后产出的 arbitrary property 规则噪音。
// Tailwind v3 提取器对 content 文件全文逐 token 扫描（含注释）无法剥离注释，
// blocklist 又只支持候选精确串匹配（无通配符，按 id 枚举不可持续），故在
// 生成后统一剥除 `.[fenix-ignore\:xxx]{fenix-ignore:xxx}` 形态规则——属性名
// fenix-ignore 非法、浏览器本就静默丢弃，剥除零运行时影响且对新增标注免疫。
// 本步骤 fail-open：任何异常不得阻塞构建（prebuild && 链）。
import { readFileSync, writeFileSync, existsSync } from 'node:fs';

const file = process.argv[2];
try {
  if (!file || !existsSync(file)) {
    console.log(`[strip-fenix-ignore-css] skip: ${file ?? '<no path>'} not found`);
  } else {
    const css = readFileSync(file, 'utf8');
    const stripped = css.replace(
      /\.\\\[fenix-ignore\\?:[0-9a-z]+\\?\]\{\s*fenix-ignore\s*:\s*[0-9a-z]+\s*;?\s*\}/g,
      ''
    );
    if (stripped !== css) {
      writeFileSync(file, stripped);
      console.log(
        `[strip-fenix-ignore-css] removed ${css.length - stripped.length} bytes of fenix-ignore rule noise`
      );
    }
  }
} catch (err) {
  console.log(`[strip-fenix-ignore-css] fail-open: ${err?.message ?? err}`);
}
process.exit(0);
