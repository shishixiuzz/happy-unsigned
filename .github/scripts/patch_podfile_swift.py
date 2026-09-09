#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject Swift 5 language mode into Podfile's post_install for pods that
cannot handle Swift 6 strict concurrency.

WHY A WHITELIST, NOT 'skip all Expo pods'
-----------------------------------------
Run 34395393255/34397458957/34400666907 (Xcode 26.3 / Swift 7, per-pod
swift_version) proved ONLY 4 pods actually compile with `-swift-version 6`
(log-verified: grep 'swift-version 6' on build output):
  ExpoModulesCore / ExpoLogBox / ExpoSplashScreen / ExpoNotifications
(expo-modules-core 55.0.17 needs Swift 6 for SE-0447 isolated conformances
`extension X: @MainActor P`; the others merely DECLARE swift_version=6.0.)

Of those, expo-notifications 55.0.27 is NOT adapted to Swift 6 concurrency —
it hits hard errors that @unchecked Sendable CANNOT fix (sending/region-based
isolation, non-Sendable results out of actor-isolated funcs). It must compile
in Swift 5. ExpoLogBox/ExpoSplashScreen DO compile clean in Swift 6 (after
patch_swift6_concurrency.py fixes their `static let shared`), so they stay 6.

So: everything EXCEPT the 4 pods that provably pass at Swift 6 is forced to
SWIFT_VERSION=5.0 + SWIFT_STRICT_CONCURRENCY=minimal.

用法: python3 patch_podfile_swift.py [path/to/Podfile]
默认: ios/Podfile
"""
import io
import sys

podfile = sys.argv[1] if len(sys.argv) > 1 else 'ios/Podfile'

# Target names that keep their podspec swift_version (6.0). Log-proven to
# compile clean under Swift 6 language mode on Xcode 26.3 / Swift 7.
SWIFT6_TARGETS = ['ExpoModulesCore', 'Expo', 'ExpoLogBox', 'ExpoSplashScreen']

with io.open(podfile, encoding='utf-8') as f:
    s = f.read()

targets_literal = '[' + ', '.join("'%s'" % t for t in SWIFT6_TARGETS) + ']'
inject = """    # CI: force Swift 5 language mode for all pods except the 4 that provably
    # pass Swift 6 (ExpoModulesCore needs 6 for SE-0447; Expo/ExpoLogBox/
    # ExpoSplashScreen compile clean at 6). Everything else — including
    # expo-notifications (NOT Swift-6-adapted: sending/isolation hard errors)
    # and all third-party pods — is downgraded to Swift 5 to avoid the
    # strict-concurrency error class entirely.
    swift6 = %s
    installer.pods_project.targets.each do |target|
      next if swift6.include?(target.name)
      target.build_configurations.each do |config|
        config.build_settings['SWIFT_VERSION'] = '5.0'
        config.build_settings['SWIFT_STRICT_CONCURRENCY'] = 'minimal'
      end
    end
""" % targets_literal

marker = 'installer.pods_project.targets.each do |target|'
if marker not in s:
    needle = 'post_install do |installer|'
    assert needle in s, 'post_install block not found in %s' % podfile
    s = s.replace(needle, needle + '\n' + inject, 1)
    with io.open(podfile, 'w', encoding='utf-8') as f:
        f.write(s)
    print('post_install patched OK (swift6=%s)' % targets_literal)
else:
    print('already patched (swift6=%s)' % targets_literal)
