#!/usr/bin/env node
// flatten-ios-target.mjs
//
// 目的：把 node_modules 里所有会参与 CocoaPods 解析的 pod 的 iOS 平台最低版本，
//       统一下调到目标部署版本（默认 15.0）。供 TrollStore 无签名构建，修复
//       "pod X ... required a higher minimum deployment target"。
//
// 为什么用 Node 而不是 `find -L | perl`：
//   pnpm 里 node_modules 是 symlink，`find -L` 在 macOS/BSD 上跟随语义不可靠，
//   之前 Expo/Hermes 的 podspec 从未被扫到。Node 用 realpathSync 取真实路径必中。
//
// 用法：node scripts/flatten-ios-target.mjs <appDir> [target]
//   <appDir>: 应用包目录（含源码），如 packages/happy-app
//   [target]: 目标 iOS 版本，缺省 15.0
//
// 同时扫 <appDir> 及其各级上层目录的 node_modules（pnpm 可能 hoist 依赖到仓库根）。

import {
  readFileSync, writeFileSync, statSync, realpathSync, readdirSync, lstatSync,
} from 'node:fs';
import { join, basename, relative, dirname } from 'node:path';

const [appDir, rawTarget] = process.argv.slice(2);
if (!appDir) {
  console.error('usage: node scripts/flatten-ios-target.mjs <appDir> [target]');
  process.exit(2);
}
const TARGET = rawTarget || '15.0';
if (!/^\d+\.\d+$/.test(TARGET)) {
  console.error(`bad target '${TARGET}'`);
  process.exit(2);
}

// ---- 收集候选 node_modules 根（app 的 + 逐级向上，容 pnpm hoist）----
const candidateRoots = [];
let cur = appDir;
for (let i = 0; i < 4; i++) { // 上限 4 层：app -> ... -> 仓库根（pnpm 正常 hoist 也就到这里）
  const cand = join(cur, 'node_modules');
  if (statSync(cand, { throwIfNoEntry: false })?.isDirectory()) candidateRoots.push(cand);
  const parent = dirname(cur);
  if (parent === cur) break;
  cur = parent;
}
const NM_roots = [...new Set(candidateRoots)];
console.log(`== 扫描节点 (target=${TARGET}) ==`);
for (const r of NM_roots) console.log(`  candidate: ${r}`);
if (NM_roots.length === 0) {
  console.error(`!! 未发现任何 node_modules —— appDir=<${appDir}> 有误或依赖未安装`);
  process.exit(1);
}

// ---- 平台版本替换 ----
// A) 窄规则：字面量形态（:ios => "x.y" / platform :ios,"x.y" / .deployment_target）
// B) 宽规则：含平台关键字的一行内，任何 "x.y" 都压（覆盖 RNScreens 这类
//    `min_supported_ios_version = new_arch_enabled ? "15.1" : "15.1"` 变量赋值式）。
// 关键字 row 不含普通依赖版本号，所以不会误伤如 podspec.version = "0.83.1"。
function doFlatten(text) {
  let changed = false;
  const what = new Set();
  const rules = [
    [/[:, ]\s*:ios\s*=>\s*(['"])\d+\.\d+\1/g, 'platforms[:ios]=>'],
    [/\.deployment_target\s*=\s*(['"])\d+\.\d+\1/g, 'deployment_target'],
    [/\bplatform\s*=\s*:ios\s*,\s*(['"])\d+\.\d+\1/g, 'platform=:ios'],
    [/\bplatform\s+:ios\s*,\s*(['"])\d+\.\d+\1/g, 'platform :ios'],
  ];
  // A) 窄规则
  for (const [re, label] of rules) {
    const next = text.replace(re, (mm) => {
      changed = true; what.add(label);
      return mm.replace(/\d+\.\d+/, TARGET);
    });
    text = next;
  }
  // B) 行级宽规则：含平台/部署关键字的行内，替换所有两位小数引号版本
  const kw = /(platforms|platform|deployment_target|min_supported|ios_version|:ios\s*=>|IOS_VERSION|deployment)/;
  text = text.replace(/^[^\n]*$/gm, (line) => {
    if (!kw.test(line)) return line;
    return line.replace(/(['"])\d+\.\d+\1/g, (m) => {
      changed = true; what.add('wide-line');
      return m.replace(/\d+\.\d+/, TARGET);
    });
  });
  return { text, changed, what };
}

// ---- 压平激励链：收集所有真实 .podspec 与 react-native helpers.rb ----
const seenGlobal = new Set();
const podspecFiles = [];
const helpersFiles = [];

function scanRoot(root) {
  function walk(dir, depth = 0) {
    if (depth > 8) return;
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.name === '.bin' || e.name === '.cache' || e.name === '.git' || e.name === '.pnpm') continue;
      const full = join(dir, e.name);
      let real;
      try { real = realpathSync(full); } catch { continue; }
      if (seenGlobal.has(real)) continue;
      seenGlobal.add(real);
      if (e.isDirectory() || lstatSync(full).isSymbolicLink()) {
        walk(real, depth + 1);
      } else if (basename(real).endsWith('.podspec')) {
        podspecFiles.push(real);
      } else if (basename(real) === 'helpers.rb' && real.includes('react-native')) {
        helpersFiles.push(real);
      }
    }
  }
  walk(root, 0);
}
for (const root of NM_roots) scanRoot(root);

console.log(`podspec files: ${podspecFiles.length}`);
console.log(`rn helpers.rb: ${helpersFiles.length}`);
if (podspecFiles.length === 0) {
  console.error('!! 未找到任何 .podspec —— 依赖未安装，或 pnpm 结构不在预期位置');
  process.exit(1);
}

// ---- 压平所有 podspec ----
const touched = [];
for (const f of podspecFiles) {
  const orig = readFileSync(f, 'utf8');
  const { text, changed, what } = doFlatten(orig);
  if (changed) {
    writeFileSync(f, text);
    touched.push(`${relative(NM_roots[0], f)} [${[...what].join(',')}]`);
  }
}
touched.sort();

// ---- RN helpers.rb：min_ios_version_supported ----
const rnHelper = helpersFiles.find((f) => f.includes('/react-native/scripts/cocoapods/helpers.rb'))
  || helpersFiles[0];
if (rnHelper) {
  const orig = readFileSync(rnHelper, 'utf8');
  const patched = orig.replace(
    /(def self\.min_ios_version_supported\b[\s\S]*?return\s*['"])\d+\.\d+(['"])/,
    (w, head, tail) => head + TARGET + tail
  );
  if (patched !== orig) {
    writeFileSync(rnHelper, patched);
    console.log(`RN helpers.rb min_ios_version_supported -> ${TARGET}`);
  } else {
    console.warn('RN helpers.rb 未命中（可能已为目标或格式不同）');
  }
} else {
  console.warn('!! 未找到 RN helpers.rb —— min_ios_version_supported 未改');
}

console.log('== touched podspec ==');
for (const c of touched.slice(0, 100)) console.log(`  - ${c}`);
if (touched.length > 100) console.log(`  ... +${touched.length - 100} 更多`);

// ---- 硬断言：关键 pod 必须命中，否则 fail loud（杜绝打地鼠静默循环）----
// 用 basename 匹配（pnpm realpath 可能形如 .pnpm/.../node_modules/expo，不含字面
// <repo>/node_modules/expo/ 前缀，不能用 relative 后的全路径匹配）。
const names = touched.map((t) => t.split(' [')[0]);
const bases = names.map((n) => n.split(/[\\/]/).pop().replace(/\.podspec$/, ''));
const mustHit = ['expo', 'expo-modules-core', 'hermes-engine'];
const missing = mustHit.filter((frag) =>
  !names.some((n) => n.includes(frag)) && !bases.some((b) => b.startsWith(frag)));
if (missing.length) {
  console.error(`!! 关键 pod 未命中：${missing.join(', ')} —— 仍会报 higher min target，终止。`);
  process.exit(1);
}

console.log(`✔ 关键 pod 已压平到 iOS ${TARGET} (touched ${touched.length})`);
process.exit(0);