#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch Swift 6 language-mode concurrency errors in the Expo pods that
compile with -swift-version 6.

WHY THIS SCRIPT EXISTS
----------------------
Swift 6.2+/7 + Swift 6 language mode makes `static let shared = X()` a hard
ERROR when X is a non-Sendable class:

    error: static property 'shared' is not concurrency-safe because
           non-'Sendable' type 'X' may have shared mutable state
    note: add '@MainActor' to make static property 'shared' part of global actor 'MainActor'

★ NOT @MainActor: that cascades isolation to every call site of `X.shared`
(verified: 17 cascade errors on expo-splash-screen).

★ Syntax position: @unchecked Sendable is a CONFORMANCE marker, valid ONLY in
the INHERITANCE CLAUSE:
    public class X: NSObject, P, @unchecked Sendable {
Putting it in declaration-attribute position is a syntax error:
    @unchecked Sendable public class X ...  →  'expressions are not allowed at
    the top level' + 'unchecked' attribute only applies in inheritance clauses'
(run 34395393255 verified).

SCOPE
-----
Only pods that actually compile in Swift 6 language mode need this. Derived
from build logs, exactly 4 pods use `-swift-version 6`:
ExpoModulesCore / ExpoLogBox / ExpoSplashScreen / ExpoNotifications
(all other pods compile as Swift 5 — patch_podfile_swift.py handles that).
This script scans those 4 source trees for the `static let shared = X()`
pattern and, when X is a co-located non-Sendable class, adds `@unchecked
Sendable` to X's inheritance clause. Idempotent. Skips structs/actors (value
semantics / inherently Sendable) and classes already marked Sendable.

用法: python3 patch_swift6_concurrency.py <repo_root>
"""
import io
import os
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else '.'

POD_SOURCE_DIRS = [
    'node_modules/expo-splash-screen/ios',
    'node_modules/expo-notifications/ios',
    'node_modules/expo-modules-core/ios',
    'node_modules/expo-log-box/ios',
]

# `static let shared = X(` / `static var shared = X(` — capture the type X.
# 声明行若已带 nonisolated / @MainActor（已是安全注释，如
# `nonisolated(unsafe) static let shared = X()`）则不在此列。
SHARED_RE = re.compile(
    r'^(?![^\n]*\b(?:nonisolated|@MainActor)\b)'
    r'[^\n]*\bstatic\s+(?:let|var)\s+shared\s*=\s*(\w+)\s*\(',
    re.MULTILINE,
)
# Idempotency / already-Sendable check against the header text.
HEADER_SENDABLE_RE = re.compile(r'Sendable|@MainActor|nonisolated')


def find_class_header(src: str, type_name: str):
    """Find the span of the FIRST `class TYPE ... {` header (may span lines).

    Returns (start, end, brace_pos_in_header) or None. The inheritance clause
    is whatever sits between `class TYPE` and the first `{`; skipping any class
    whose header already mentions Sendable / @MainActor / nonisolated.
    """
    pat = re.compile(
        r'\bclass\s+' + re.escape(type_name) + r'\s*(?::[^{]*?)(\{)',
        re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        return None
    header = m.group(0)
    if HEADER_SENDABLE_RE.search(header):
        return None
    return (m.start(), m.end(), header.rfind('{'))


def patch_file(path: str) -> str:
    """Patch one Swift file. Returns a status string."""
    with io.open(path, encoding='utf-8') as f:
        src = f.read()

    # 先收集所有补丁（(start, end, brace_offset_in_header, type_name)），
    # 再按 start 从大到小应用，保证前面插入不会弄乱后面匹配的偏移。
    pending = []
    for m in SHARED_RE.finditer(src):
        type_name = m.group(1)
        hit = find_class_header(src, type_name)
        if hit is None:
            continue  # struct / actor / already Sendable / declared elsewhere
        hs, he, brace_off = hit
        pending.append((hs, he, brace_off, type_name))

    if not pending:
        return 'clean (no action)'

    # 从后往前应用补丁，偏移互不干扰。
    for hs, he, _bp, _tn in sorted(pending, reverse=True):
        header = src[hs:he]
        bp = header.rfind('{')
        head = header[:bp].rstrip()          # 去掉继承子句尾部空白
        new_header = head + ', @unchecked Sendable ' + header[bp:]
        src = src[:hs] + new_header + src[he:]

    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    msgs = []
    for hs, _he, _bp, type_name in pending:
        msgs.append('%s:%d -> class %s @unchecked Sendable' % (
            os.path.basename(path), src.count('\n', 0, hs) + 1, type_name))
    return 'PATCHED | ' + '; '.join(msgs)


def main() -> int:
    changed = 0
    for rel in POD_SOURCE_DIRS:
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            print('SKIP dir (not present): %s' % rel)
            continue
        for dirpath, _dirnames, filenames in os.walk(d):
            for fn in sorted(filenames):
                if not fn.endswith('.swift'):
                    continue
                p = os.path.join(dirpath, fn)
                rel_p = os.path.relpath(p, root).replace('\\', '/')
                status = patch_file(p)
                if status.startswith('PATCHED'):
                    changed += 1
                    print('%s' % status)
    print('total files patched: %d' % changed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
