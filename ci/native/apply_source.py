#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install this native target into the pinned GammaOS worktree."""
from pathlib import Path
import argparse
import shutil


def apply(source, support):
    target = source/'device/gameconsole/r36h'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(support/'device/gameconsole/r36h', target)
    bp = source/'vendor/rockchip/common/bin/arm64/Android.bp'
    extra = (support/'vendor/rockchip/common/bin/arm64/Android.bp').read_text()
    # This file does not exist in the pinned GammaOS source. We own its
    # generated definition and must refresh it on cached source checkouts.
    bp.write_text(extra)
    # WSL1 rejects mmap of zero-byte files (microsoft/WSL#3451). A newline
    # is an empty Ninja program and is also harmless in the epoch marker.
    bootstrap = source/'build/soong/ui/build/soong.go'
    text = bootstrap.read_text()
    old = 'err = ioutil.WriteFile(path, nil, 0666)'
    new = r'err = ioutil.WriteFile(path, []byte("\n"), 0666)'
    if text.count(old) == 1:
        bootstrap.write_text(text.replace(old, new))
    elif new not in text:
        raise ValueError('Unexpected Soong bootstrap placeholder writer')
    init = source/'system/core/rootdir/init.rc'
    text = init.read_text()
    token = '    start rgp2xbox\n'
    marker = '    # Native R36H input is provided by the kernel gamepad driver.\n'
    if token in text:
        if text.count(token) != 1:
            raise ValueError('Unexpected GammaOS controller startup layout')
        init.write_text(text.replace(token, marker))
    elif marker not in text:
        raise ValueError('Cannot locate GammaOS controller startup')
    # GammaOS invokes customization at boot and exposes setup from its UI.
    # Both must follow this board's native flow; the original setup can flash
    # an RK3566 boot image and restore another device's Magisk data tree.
    for name in ('setup.sh', 'customization.sh'):
        shutil.copyfile(target/'firstboot.sh', source/'device/google/atv/gammaos'/name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('support', type=Path)
    args = parser.parse_args()
    apply(args.source.resolve(), args.support.resolve())
