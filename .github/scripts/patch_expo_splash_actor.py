#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch expo-splash-screen's SplashScreenManager to be @unchecked Sendable.

expo-splash-screen 55.0.12 declares `@objc static let shared = SplashScreenManager()`
on a plain class. When that pod is compiled in Swift 6 language mode
(expo-splash-screen keeps its podspec's swift_version=6.0 in our per-pod setup),
Swift 6.2+/7 strict concurrency turns this into a hard ERROR:

    error: static property 'shared' is not concurrency-safe because
           non-'Sendable' type 'SplashScreenManager' may have shared mutable state
    note: add '@MainActor' to make static property 'shared' part of global actor 'MainActor'

★ NOT @MainActor: that cascades isolation to every call site
(SplashScreenModule accesses shared.setOptions/hide/preventAutoHideCalled from
nonisolated contexts -> 17 errors). The class is an AppDelegate-level UI
singleton used only on the main thread, so @unchecked Sendable is the surgical
fix: it satisfies the static-let concurrency check without changing isolation.

★★ SYNTAX POSITION — @unchecked Sendable goes in the INHERITANCE CLAUSE,
   NOT in declaration-attribute position! (Run 34395393255 failed here.)
   `@unchecked Sendable public class X: ...` is INVALID:
     error: expressions are not allowed at the top level
     error: 'unchecked' attribute only applies in inheritance clauses
   The attribute-form `@unchecked Sendable` on a class is only valid for
   @MainActor-style GLOBAL ACTOR attributes. For conformance marking, write:
     public class SplashScreenManager: NSObject, RCTReloadListener, @unchecked Sendable {
   (canonical SE-0302 form, matches the compiler's own suggestion)

用法: python3 patch_expo_splash_actor.py <repo_root>
幂等：类已含 '@unchecked Sendable'（继承子句里）时直接打印 skipped。
"""
import io
import os
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else '.'
path = os.path.join(
    root,
    'node_modules', 'expo-splash-screen', 'ios', 'SplashScreenManager.swift',
)

with io.open(path, encoding='utf-8') as f:
    src = f.read()

# 幂等：继承子句里已带 @unchecked Sendable 就跳过。
if re.search(r'class\s+SplashScreenManager[^{]*@unchecked Sendable', src):
    print('SKIP: SplashScreenManager already @unchecked Sendable')
    sys.exit(0)

# 把 @unchecked Sendable 追加到继承子句末尾（superclass 和 protocols 之后）。
# 兼容 `class X:` 与 `public class X:` 两种安装包写法；继承列表用 [^{]+? 惰性匹配。
new, n = re.subn(
    r'((?:public\s+)?)class\s+SplashScreenManager\s*:\s*([^{]+?)\s*(\{)',
    r'\1class SplashScreenManager: \2, @unchecked Sendable \3',
    src,
    count=1,
)
assert n == 1, 'failed to match class declaration in %s' % path
src = new

with io.open(path, 'w', encoding='utf-8') as f:
    f.write(src)
print('PATCHED: %s -> class ...: ..., @unchecked Sendable' % path)
