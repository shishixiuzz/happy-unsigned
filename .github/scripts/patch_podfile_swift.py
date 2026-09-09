#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject Swift 5 language mode into Podfile's post_install for non-Expo pods.

RN 生态里有些 podspec 声明 swift_version=6.0 但代码没适配 Swift 6 并发
（vision-camera 4.7.3 实测报 main-actor/global-state 错误）。Expo 系
（Expo/ExpoModulesCore/ExpoLogBox/expo-*）真的用了 Swift 6 的
@MainActor attribute 语法，必须保留 6.0。所以遍历 Pods targets：
  非 Expo 官方 pod → SWIFT_VERSION=5.0 + strict concurrency=minimal
  Expo 系 → 保持 podspec 声明的 6.0

用法: python3 patch_podfile_swift.py [path/to/Podfile]
默认: ios/Podfile
"""
import io
import sys

podfile = sys.argv[1] if len(sys.argv) > 1 else 'ios/Podfile'

with io.open(podfile, encoding='utf-8') as f:
    s = f.read()

inject = """    # CI: force Swift 5 language mode for all non-Expo pods
    installer.pods_project.targets.each do |target|
      next if target.name.start_with?('Expo', 'expo')
      target.build_configurations.each do |config|
        config.build_settings['SWIFT_VERSION'] = '5.0'
        config.build_settings['SWIFT_STRICT_CONCURRENCY'] = 'minimal'
      end
    end
"""

marker = 'installer.pods_project.targets.each do |target|'
if marker not in s:
    needle = 'post_install do |installer|'
    assert needle in s, 'post_install block not found in %s' % podfile
    s = s.replace(needle, needle + '\n' + inject, 1)
    with io.open(podfile, 'w', encoding='utf-8') as f:
        f.write(s)
    print('post_install patched OK')
else:
    print('already patched')
