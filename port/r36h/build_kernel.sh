#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
support=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cache=$(realpath -m -- "$1")
output=$(realpath -m -- "$2")
jobs=${BUILD_JOBS:-32}
[[ "$jobs" =~ ^[1-9][0-9]?$ && "$jobs" -le 64 ]]
cpus=$(nproc)
if (( jobs > cpus )); then jobs=$cpus; fi
printf 'Kernel parallel jobs: %s; available CPUs: %s\n' "$jobs" "$cpus"
mkdir -p "$cache" "$output"
export DEBIAN_FRONTEND=noninteractive GIT_TERMINAL_PROMPT=0
# The versioned multilib packages can coexist with this compiler; the generic
# gcc-multilib metapackage cannot. Its installed runtime dependencies remain.
apt-get install -y --no-install-recommends gcc-12-aarch64-linux-gnu binutils-aarch64-linux-gnu
python3 -u "$support/fetch_sources.py" "$cache"
R36H_REFERENCE_DIR="$cache/boards" python3 -m unittest discover -s "$support/tests" -v
kernel="$cache/kernel-95a3ad83f7f9"
objects="$cache/kernel-out-native"
mkdir -p "$objects"
cp "$support/r36h-joypad.c" "$kernel/drivers/input/joystick/r36h-joypad.c"
if ! grep -q '^config JOYSTICK_R36H$' "$kernel/drivers/input/joystick/Kconfig"; then
    cat >> "$kernel/drivers/input/joystick/Kconfig" <<'KCONFIG'

config JOYSTICK_R36H
    tristate "R36H GPIO and ADC-multiplexer gamepad"
    depends on OF && GPIOLIB && IIO
KCONFIG
fi
if ! grep -q 'CONFIG_JOYSTICK_R36H' "$kernel/drivers/input/joystick/Makefile"; then
    echo 'obj-$(CONFIG_JOYSTICK_R36H) += r36h-joypad.o' >> "$kernel/drivers/input/joystick/Makefile"
fi
for profile in v20 v21; do
    python3 "$support/port_dts.py" "$cache/boards/r36h-$profile.dtb" \
        "$kernel/arch/arm64/boot/dts/rockchip/rk3326-r36h-$profile.dts" --profile "$profile"
done
kmake=(make -C "$kernel" O="$objects" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CC=aarch64-linux-gnu-gcc-12)
"${kmake[@]}" rockchip_defconfig
python3 "$support/configure_kernel.py" --source "$kernel" --config "$objects/.config" --fragment "$support/kernel.fragment"
"${kmake[@]}" olddefconfig
python3 "$support/configure_kernel.py" --source "$kernel" --config "$objects/.config" --fragment "$support/kernel.fragment" --audit > "$output/kernel-config-audit.json"
"${kmake[@]}" -j"$jobs" Image rockchip/rk3326-r36h-v20.dtb rockchip/rk3326-r36h-v21.dtb
"${kmake[@]}" headers_install INSTALL_HDR_PATH="$output/headers"
[[ -s "$output/headers/include/linux/types.h" && -s "$output/headers/include/asm/unistd.h" ]]
cp "$objects/arch/arm64/boot/Image" "$output/Image"
cp "$objects/arch/arm64/boot/dts/rockchip/"rk3326-r36h-v{20,21}.dtb "$output/"
cp "$objects/.config" "$output/kernel.config"
python3 - "$output" <<'PY'
import pathlib,struct,sys
root=pathlib.Path(sys.argv[1]);p=root/'Image'
with p.open('rb') as f: header=f.read(64)
assert header[56:60] == b'ARM\x64', 'Missing ARM64 Image header'
for p in root.glob('*.dtb'):
    with p.open('rb') as f: header=f.read(8)
    magic,size=struct.unpack('>2I',header)
    assert magic==0xd00dfeed and size==p.stat().st_size, 'Invalid DTB'
print('Native Image and R36H reference DTB headers verified')
PY
printf '%s\n' '95a3ad83f7f90e0e672b9c99b0858b4964318667' > "$output/kernel-source-commit.txt"
aarch64-linux-gnu-gcc-12 --version | head -1 > "$output/kernel-compiler.txt"
cp "$support/SOURCES.json" "$output/"
(cd "$output"; sha256sum Image *.dtb kernel.config SOURCES.json > SHA256SUMS)

