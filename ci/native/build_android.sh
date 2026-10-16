#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
support=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cache=/var/cache/gammaos-r36h-native
source_dir=$cache/android
output=$(realpath -m -- "$1")
mkdir -p "$output"
[[ -s "$cache/artifacts/kernel/Image" ]]
python3 "$support/ci/native/apply_source.py" "$source_dir" "$support"
export OUT_DIR="$cache/out-native" R36H_NATIVE_KERNEL="$cache/artifacts/kernel/Image"
export BUILD_USERNAME=gammaos BUILD_HOSTNAME=r36h-native-runner
cd "$source_dir"
python3 - <<'PY'
from pathlib import Path
import os
import struct
p=Path('vendor/rockchip/common/bin/arm64/busybox')
with p.open('rb') as f: data=f.read(64)
if len(data) != 64 or data[:6] != b'\x7fELF\x01\x01' or struct.unpack_from('<H',data,18)[0]!=40:
    raise SystemExit('Expected the upstream static ARM32 BusyBox ELF')
kernel_config = Path('/var/cache/gammaos-r36h-native/artifacts/kernel/kernel.config').read_text().splitlines()
if 'CONFIG_COMPAT=y' not in kernel_config:
    raise SystemExit('The upstream ARM32 BusyBox requires native-kernel CONFIG_COMPAT=y')
print('Verified upstream ARM32 BusyBox and kernel 32-bit execution support')
# Repair placeholders from an earlier failed bootstrap. Keep every generated
# rule in nonempty files. The source patch also handles a fresh output tree.
for ninja_file in (Path(os.environ['OUT_DIR'])/'soong').glob('globs-*.ninja'):
    if ninja_file.is_file() and ninja_file.stat().st_size == 0:
        ninja_file.write_text('\n')
        print('Repaired empty WSL1 Ninja placeholder:', ninja_file.name)
PY
# Upstream envsetup legitimately references unset shell variables.
set +u
# shellcheck disable=SC1091
source build/envsetup.sh
lunch gamma_r36h-userdebug
product_out=$(get_build_var PRODUCT_OUT)
[[ "$product_out" == "$OUT_DIR/target/product/r36h" ]]
# With 32 GiB RAM, cap Android's parallel jobs while retaining 16-way kernel
# compilation. An explicit repository variable can lower it further.
jobs=${ANDROID_BUILD_JOBS:-8}
[[ "$jobs" =~ ^[1-9][0-9]?$ && "$jobs" -le 32 ]]
m -j"$jobs" bootimage systemimage vendorimage userdataimage
set -u
for name in boot.img ramdisk.img system.img vendor.img userdata.img; do
    [[ -s "$product_out/$name" ]]
done
printf '%s\n' "$product_out" > "$cache/android-product-out.txt"
git rev-parse HEAD > "$output/android-source-commit.txt"
printf '%s\n' 'gamma_r36h-userdebug' > "$output/android-target.txt"
cp "$source_dir/device/gameconsole/r36h/BoardConfig.mk" "$output/"
cp "$source_dir/device/gameconsole/r36h/manifest.xml" "$output/vendor-manifest-source.xml"
df -h "$cache"
