#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Hydrate selected, materialized LFS paths without traversing excluded blobs.

Git LFS's full-tree scan does not work with the source repository's partial
clone: it asks for blobs inside the deliberately excluded .repo archives.
Read only committed pointer blobs for explicitly selected worktree paths.
"""
import argparse
import concurrent.futures
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

INCLUDE = (
    'prebuilts/clang/host/linux-x86/clang-r450784d/**',
    'prebuilts/clang/host/linux-x86/clang-stable/**',
    'prebuilts/clang-tools/linux-x86/**',
    'prebuilts/jdk/jdk11/linux-x86/**', 'prebuilts/rust/linux-x86/**',
    'prebuilts/go/linux-x86/**', 'prebuilts/build-tools/linux-x86/**',
    'prebuilts/sdk/**', 'prebuilts/vndk/**', 'prebuilts/module_sdk/**',
    'prebuilts/runtime/**', 'device/google/atv/gammaos/**',
    'external/kotlinc/**', 'external/chromium-webview/prebuilt/arm/**',
    'external/chromium-webview/prebuilt/arm64/**', 'packages/modules/GeoTZ/**',
    'vendor/rockchip/common/bin/arm64/busybox',
)
POINTER = re.compile(rb'version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?\Z')
PRINT_LOCK = threading.Lock()


def log(*values):
    with PRINT_LOCK:
        print(*values, flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    paths = []
    for line in (root/'.gitattributes').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        words = shlex.split(line)
        if len(words) < 2 or 'filter=lfs' not in words[1:]:
            continue
        path = words[0]
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in INCLUDE):
            continue
        if path.startswith(('/', '.repo/', 'out/')) or '..' in Path(path).parts:
            raise ValueError('Invalid selected LFS path')
        if any(token in path for token in ('*', '?', '[')):
            raise ValueError('Selected LFS attributes unexpectedly contain a glob: '+path)
        target = root/path
        if not target.is_file() or target.is_symlink():
            continue
        # The checkout already fetched these small pointer blobs. Do not scan
        # trees or ask for an excluded .repo object's contents.
        pointer = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+path])
        match = POINTER.fullmatch(pointer)
        if not match:
            raise ValueError('Committed LFS pointer is invalid: '+path)
        size = int(match[2])
        if not 0 < size <= 5*1024**3:
            raise ValueError('Unexpected LFS object size: '+path)
        paths.append({'path': path, 'oid': match[1].decode(), 'size': size})
    return paths


def batch(objects, repository):
    url = 'https://github.com/'+repository+'.git/info/lfs/objects/batch'
    payload = json.dumps({'operation': 'download', 'transfers': ['basic'],
                          'objects': [{'oid': o['oid'], 'size': o['size']} for o in objects]}).encode()
    request = urllib.request.Request(url, data=payload, headers={
        'Accept': 'application/vnd.git-lfs+json',
        'Content-Type': 'application/vnd.git-lfs+json',
        'User-Agent': 'GammaOS-R36H-native-build',
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    return {o['oid']: o for o in result.get('objects', [])}


def fetch_one(root, entry):
    target = root/entry['path']
    oid, expected = entry['oid'], entry['size']
    if target.stat().st_size == expected and sha256(target) == oid:
        log('Verified existing', entry['path'])
        return
    cache = root/'.git/lfs/objects'/oid[:2]/oid[2:4]/oid
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.is_file() and cache.stat().st_size == expected and sha256(cache) == oid:
        log('Using verified cache', entry['path'])
    else:
        error = None
        for attempt in range(3):
            # A GitHub fork may not serve the parent's LFS objects. The
            # original GammaOS repository is an equivalent source only when
            # its downloaded bytes match the exact committed SHA-256.
            repository = ('kobyfletcher08-ops/GammaOSCoreDistribution' if attempt == 0
                          else 'TheGammaSqueeze/GammaOSCoreDistribution')
            try:
                obj = batch([entry], repository).get(oid, {})
                if 'error' in obj or 'download' not in obj.get('actions', {}):
                    raise ValueError('LFS origin did not provide the committed object')
                action = obj['actions']['download']
                url = urllib.parse.urlsplit(action['href'])
                if url.scheme != 'https' or url.username or url.password:
                    raise ValueError('Invalid LFS download URL')
                temp = cache.with_suffix('.r36h-part')
                request = urllib.request.Request(action['href'], headers=action.get('header', {}))
                digest, received, last = hashlib.sha256(), 0, time.monotonic()
                log('Downloading', entry['path'], f'({expected//1024//1024} MiB)')
                with urllib.request.urlopen(request, timeout=90) as response, temp.open('wb') as output:
                    while True:
                        block = response.read(1024*1024)
                        if not block:
                            break
                        received += len(block)
                        if received > expected:
                            raise ValueError('LFS server exceeded the committed object size')
                        digest.update(block)
                        output.write(block)
                        if time.monotonic()-last >= 15:
                            log('Progress', entry['path'], f'{received//1024//1024}/{expected//1024//1024} MiB')
                            last = time.monotonic()
                if received != expected or digest.hexdigest() != oid:
                    raise ValueError('LFS SHA-256/size mismatch')
                os.replace(temp, cache)
                break
            except (OSError, ValueError, KeyError) as exc:
                # Presigned URLs and response authorization headers never
                # appear in the build log.
                error = ('HTTP '+str(exc.code) if isinstance(exc, urllib.error.HTTPError)
                         else type(exc).__name__)
                log('Retry', entry['path'], attempt+1, error)
                if attempt == 2:
                    raise RuntimeError('Cannot hydrate '+entry['path']+': '+error) from None
                time.sleep(2)
    temp_target = target.with_name(target.name+'.r36h-lfs')
    mode = target.stat().st_mode
    shutil.copyfile(cache, temp_target)
    os.chmod(temp_target, mode)
    os.replace(temp_target, target)
    log('Hydrated', entry['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    entries = inventory(root)
    report = {'objects': entries, 'bytes': sum(x['size'] for x in entries), 'complete': False}
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    log('Selected', len(entries), 'LFS objects;', round(report['bytes']/1024**3, 2), 'GiB')
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry['oid'], []).append(entry)
    def hydrate_group(group):
        for entry in group:
            fetch_one(root, entry)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(hydrate_group, grouped.values()))
    report['complete'] = True
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    log('Selected Linux/GammaOS LFS inputs are complete and verified.')


if __name__ == '__main__':
    main()
