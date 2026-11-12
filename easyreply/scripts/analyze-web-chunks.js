#!/usr/bin/env node
/**
 * 分析 expo export --platform web 的分包产物。
 *
 * 产物里 __d 的依赖表有两种形态：
 *   __d(factory, ID, [dep, dep])                       // 同步依赖
 *   __d(factory, ID, {"0":dep, "paths":{"id":"/url"}})  // 含异步 chunk 的依赖
 * 后者的 paths 把 moduleId 映射到 chunk URL，是 import() 的加载入口。
 *
 * 输出：跨 chunk 重复定义、悬空依赖（引用了首屏 chunk 与自身都没有、也没有 paths 兜底的模块）。
 * 用法：node scripts/analyze-web-chunks.js [dist/_expo/static/js/web]
 */
const fs = require('fs');
const path = require('path');

const dir = process.argv[2] || 'dist/_expo/static/js/web';

/** 从 `__d(` 处向后括号配平，返回整个调用的实参源码 */
function readCallArgs(src, openParenIdx) {
  let depth = 0;
  for (let i = openParenIdx; i < src.length; i++) {
    const c = src[i];
    if (c === '"' || c === "'" || c === '`') {
      const quote = c;
      i++;
      while (i < src.length && src[i] !== quote) {
        if (src[i] === '\\') i++;
        i++;
      }
      continue;
    }
    if (c === '(' || c === '[' || c === '{') depth++;
    else if (c === ')' || c === ']' || c === '}') {
      depth--;
      if (depth === 0) return src.slice(openParenIdx + 1, i);
    }
  }
  return null;
}

/** 把实参源码按顶层逗号切开 */
function splitTopLevel(args) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < args.length; i++) {
    const c = args[i];
    if (c === '"' || c === "'" || c === '`') {
      const quote = c;
      i++;
      while (i < args.length && args[i] !== quote) {
        if (args[i] === '\\') i++;
        i++;
      }
      continue;
    }
    if (c === '(' || c === '[' || c === '{') depth++;
    else if (c === ')' || c === ']' || c === '}') depth--;
    else if (c === ',' && depth === 0) {
      out.push(args.slice(start, i));
      start = i + 1;
    }
  }
  out.push(args.slice(start));
  return out;
}

function parseChunk(src) {
  const defs = new Set();
  const refs = new Set();
  const paths = new Map();
  let missed = 0;
  let raw = 0;
  let idx = 0;
  while ((idx = src.indexOf('__d(', idx)) !== -1) {
    raw++;
    const args = readCallArgs(src, idx + 3);
    idx += 4;
    if (args == null) {
      missed++;
      continue;
    }
    const parts = splitTopLevel(args);
    if (parts.length < 2) {
      missed++;
      continue;
    }
    const id = Number(parts[1].trim());
    if (!Number.isFinite(id)) {
      missed++;
      continue;
    }
    defs.add(id);
    const depSrc = parts.length >= 3 ? parts.slice(2).join(',').trim() : '';
    if (!depSrc) continue;
    let depMap;
    try {
      depMap = JSON.parse(depSrc);
    } catch {
      missed++;
      continue;
    }
    if (Array.isArray(depMap)) {
      for (const d of depMap) refs.add(d);
    } else if (depMap && typeof depMap === 'object') {
      for (const [k, v] of Object.entries(depMap)) {
        if (k === 'paths') {
          for (const [pid, url] of Object.entries(v)) paths.set(Number(pid), url);
        } else if (typeof v === 'number') {
          refs.add(v);
        }
      }
    }
  }
  return { defs, refs, paths, missed, raw };
}

const files = fs.readdirSync(dir).filter((f) => f.endsWith('.js'));
const perChunk = new Map();
const rawSrc = new Map();
for (const f of files) {
  const src = fs.readFileSync(path.join(dir, f), 'utf8');
  rawSrc.set(f, src);
  perChunk.set(f, parseChunk(src));
}

/**
 * 括号配平解析对压缩产物偶有漏判（正则/模板串里的括号），会造成「悬空依赖」误报。
 * 报告前再按 `,<id>,[` / `,<id>,{` 做一次文本兜底确认。
 */
function definedSomewhere(id) {
  const a = `,${id},[`;
  const b = `,${id},{`;
  for (const src of rawSrc.values()) {
    if (src.includes(a) || src.includes(b)) return true;
  }
  return false;
}

const owner = new Map();
for (const [f, v] of perChunk) {
  for (const id of v.defs) {
    if (!owner.has(id)) owner.set(id, []);
    owner.get(id).push(f);
  }
}

const eager = files.filter((f) => /^(__common-|entry-|__expo-metro-runtime-)/.test(f));
const eagerIds = new Set();
for (const [id, cs] of owner) if (cs.some((c) => eager.includes(c))) eagerIds.add(id);

let missedTotal = 0;
for (const [f, v] of perChunk) {
  if (v.missed) {
    missedTotal += v.missed;
    console.log(`  解析失败 ${f}: ${v.missed}/${v.raw}`);
  }
}
console.log(`解析失败合计: ${missedTotal}`);
console.log(`首屏 chunk: ${eager.join(', ')}`);
console.log(`总定义 moduleId: ${owner.size}，首屏定义: ${eagerIds.size}`);

console.log('\n== 跨 chunk 重复定义 ==');
let dup = 0;
for (const [id, cs] of owner) {
  if (cs.length > 1) {
    dup++;
    if (dup <= 20) console.log(`  ${id} -> ${cs.join(' , ')}`);
  }
}
console.log(`  合计: ${dup}`);

console.log('\n== 悬空依赖（首屏/自身/paths 都覆盖不到）==');
let bad = 0;
for (const f of files) {
  if (eager.includes(f)) continue;
  const { defs, refs, paths } = perChunk.get(f);
  const dangling = [...refs].filter(
    (d) => !eagerIds.has(d) && !defs.has(d) && !paths.has(d) && !definedSomewhere(d),
  );
  if (!dangling.length) continue;
  bad += dangling.length;
  console.log(
    `  ${f}\n      ${dangling
      .map((d) => `${d}@${owner.has(d) ? owner.get(d).join('|') : 'NOWHERE'}`)
      .join('  ')}`,
  );
}
if (!bad) console.log('  (无)');

console.log('\n== 异步 chunk 的 paths 目标文件是否存在 ==');
let missingFile = 0;
for (const [f, v] of perChunk) {
  for (const [id, url] of v.paths) {
    const target = path.join(dir, path.basename(url));
    if (!fs.existsSync(target)) {
      missingFile++;
      console.log(`  ${f} 引用了不存在的 chunk: ${url} (module ${id})`);
    }
  }
}
if (!missingFile) console.log('  (全部存在)');
