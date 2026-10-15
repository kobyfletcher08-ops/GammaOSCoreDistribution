#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fetch pinned, independent sources and checksum-verified board references."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request


def download(url, path, expected=None):
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS source downloads are supported')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and expected and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return
    tmp = path.with_suffix(path.suffix+'.partial')
    with urllib.request.urlopen(url, timeout=90) as response, tmp.open('wb') as target:
        for block in iter(lambda: response.read(1024*1024), b''):
            target.write(block)
    if expected and hashlib.sha256(tmp.read_bytes()).hexdigest() != expected:
        raise ValueError('Source SHA-256 mismatch: '+path.name)
    tmp.replace(path)


def checkout(cache, entry, name):
    repo, commit = entry['repository'], entry['commit']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+', repo) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid source pin')
    dest = cache/(name+'-'+commit[:12])
    dest.mkdir(parents=True, exist_ok=True)
    def git(*args, **kwargs):
        return subprocess.run(['git', '-C', str(dest), *args], check=True, **kwargs)
    if not (dest/'.git').is_dir():
        git('init')
        git('remote', 'add', 'origin', 'https://github.com/'+repo+'.git')
    existing = subprocess.run(['git', '-C', str(dest), 'rev-parse', '--verify', 'HEAD'], capture_output=True, text=True)
    if existing.returncode == 0:
        if existing.stdout.strip() != commit:
            raise ValueError('Source cache contains a different commit: '+str(dest))
        return dest
    git('-c', 'core.autocrlf=false', 'fetch', '--no-tags', '--depth=1', 'origin', commit)
    git('-c', 'core.autocrlf=false', 'checkout', '--detach', commit)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--boards-only', action='store_true')
    args = parser.parse_args()
    source = json.loads(Path(__file__).with_name('SOURCES.json').read_text())
    for profile, entry in source['board_profiles'].items():
        download(entry['url'], args.cache/'boards'/('r36h-'+profile+'.dtb'), entry['sha256'])
        print('Verified reference', profile, entry['reference_model'], flush=True)
    if not args.boards_only:
        for key in ('kernel', 'u_boot'):
            path = checkout(args.cache, source[key], key)
            print('Pinned source', key, path, flush=True)
        entry = source['rkbin']
        download('https://raw.githubusercontent.com/'+entry['repository']+'/'+entry['commit']+'/'+entry['bl31'],
                 args.cache/'rkbin'/Path(entry['bl31']).name)


if __name__ == '__main__':
    main()
