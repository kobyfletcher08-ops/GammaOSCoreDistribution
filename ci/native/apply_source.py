#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install this native target into the pinned GammaOS worktree."""
from pathlib import Path
import argparse
import shutil


def configure_busybox(source):
    path = source/'vendor/rockchip/common/bin/Android.mk'
    text = path.read_text()
    original = '''include $(CLEAR_VARS)
LOCAL_MODULE := busybox
LOCAL_MODULE_CLASS := EXECUTABLES
LOCAL_MODULE_STEM := $(LOCAL_MODULE)
LOCAL_SRC_FILES := $(TARGET_ARCH)/$(LOCAL_MODULE)
include $(BUILD_PREBUILT)
'''
    guarded = ('# The native R36H Soong module owns /system/bin/busybox.\n'
               'ifneq ($(TARGET_DEVICE),r36h)\n'+original+'endif\n')
    if guarded in text:
        return
    if text.count(original) != 1:
        raise ValueError('Unexpected legacy Rockchip BusyBox module')
    path.write_text(text.replace(original, guarded))


def apply(source, support, kernel_headers):
    if not (kernel_headers/'include/linux/types.h').is_file() or not (kernel_headers/'include/asm/unistd.h').is_file():
        raise ValueError('Missing exported native ARM64 kernel UAPI headers')
    target = source/'device/gameconsole/r36h'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(support/'device/gameconsole/r36h', target)
    shutil.copytree(kernel_headers, target/'kernel-headers')
    bp = source/'vendor/rockchip/common/bin/arm64/Android.bp'
    extra = (support/'vendor/rockchip/common/bin/arm64/Android.bp').read_text()
    # This file does not exist in the pinned GammaOS source. We own its
    # generated definition and must refresh it on cached source checkouts.
    bp.write_text(extra)
    # The same ARM32 payload also has an upstream Make definition. Keep our
    # correctly declared 32-bit Soong module as its sole installer on R36H.
    configure_busybox(source)
    # Keep the existing Lineage header module interface, using the sanitized
    # headers from our separate native kernel build. No Lineage kernel make
    # variables or a second kernel source checkout are needed inside Soong.
    lineage_bp = source/'vendor/lineage/build/soong/Android.bp'
    text = lineage_bp.read_text()
    anchor = 'lineage_generator {\n    name: "generated_kernel_includes",'
    start = text.find(anchor)
    end = text.find('\ncc_library_headers {', start)
    if start < 0 or end < 0 or text.count(anchor) != 1:
        raise ValueError('Unexpected Lineage generated kernel header module')
    generator = '''lineage_generator {
    name: "generated_kernel_includes",
    // Native R36H UAPI headers exported by Rockchip 5.10 headers_install.
    cmd: "cp -a device/gameconsole/r36h/kernel-headers/. $(genDir)/",
    export_include_dirs: ["include"],
    dep_root: "device/gameconsole/r36h/kernel-headers",
    dep_files: ["include/**/*"],
}
'''
    lineage_bp.write_text(text[:start]+generator+text[end:])
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
    parser.add_argument('--kernel-headers', type=Path, required=True)
    args = parser.parse_args()
    apply(args.source.resolve(), args.support.resolve(), args.kernel_headers.resolve())

