#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch expo-splash-screen's SplashScreenManager to be @MainActor-isolated.

expo-splash-screen 55.0.12 declares `@objc static let shared = SplashScreenManager()`
on a plain class. When that pod is compiled in Swift 6 language mode
(expo-splash-screen keeps its podspec's swift_version=6.0 in our per-pod setup),
Swift 6.2+/7 strict concurrency turns this into a hard ERROR:

    error: static property 'shared' is not concurrency-safe because
           non-'Sendable' type 'SplashScreenManager' may have shared mutable state
    note: add '@MainActor' to make static property 'shared' part of global actor 'MainActor'

The class is an AppDelegate-level UI singleton (manages the splash view, listens
to NotificationCenter on the main thread), and every caller already runs in a
@MainActor context (ExpoAppDelegateSubscriber / ExpoModulesCore Module are both
MainActor-isolated in SDK 55), so the compiler-suggested fix is safe and matches
upstream: newer expo-splash-screen added @MainActor on the class.

用法: python3 patch_expo_splash_actor.py <repo_root>
幂等：已含 '@MainActor class SplashScreenManager' 时直接打印 skipped。
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

if re.search(r'@MainActor\s+(?:public\s+)?class SplashScreenManager', src):
    print('SKIP: SplashScreenManager already @MainActor')
    sys.exit(0)

# 安装包里的源码有两种写法：`class SplashScreenManager` 或 `public class SplashScreenManager`。
# Swift 语法要求 attribute（@MainActor）在访问控制符（public）之前，
# 所以必须把 @MainActor 插在 class 关键字正前方，不能简单前置到整行。
new, n = re.subn(
    r'(\b(?:public\s+)?)class\s+SplashScreenManager\s*:\s*NSObject,\s*RCTReloadListener\s*\{',
    r'@MainActor \1class SplashScreenManager: NSObject, RCTReloadListener {',
    src,
    count=1,
)
assert n == 1, 'failed to match class declaration in %s' % path
src = new

with io.open(path, 'w', encoding='utf-8') as f:
    f.write(src)
print('PATCHED: %s -> @MainActor' % path)
