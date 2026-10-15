#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cache=$(realpath -- "$1")
output=$(realpath -m -- "$2")
mkdir -p "$output"
source_dir="$cache/u_boot-f919c3a889f0"
objects="$cache/uboot-out-native"
bl31="$cache/rkbin/rk3326_bl31_v1.37.elf"
[[ -s "$bl31" && -f "$source_dir/Makefile" ]]
make -C "$source_dir" O="$objects" odroid-go2_defconfig
# Keep the environment in RAM; never save it across the SD partition table.
python3 - "$objects/.config" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);rows=p.read_text().splitlines()
settings={
 'ENV_IS_IN_MMC':'n', 'ENV_IS_NOWHERE':'y', 'CMD_BOOTI':'y',
 'CMD_SYSBOOT':'y', 'CMD_FAT':'y', 'FS_FAT':'y',
 'LEGACY_IMAGE_FORMAT':'y', 'USE_BOOTCOMMAND':'y',
 'BOOTCOMMAND':'"mmc dev 0; sysboot mmc 0:1 any ${scriptaddr} /extlinux/extlinux.conf; mmc dev 1; sysboot mmc 1:1 any ${scriptaddr} /extlinux/extlinux.conf"',
}
for k,v in settings.items():
 rows=[s for s in rows if not s.startswith('CONFIG_'+k+'=') and s!='# CONFIG_'+k+' is not set']
 rows.append('# CONFIG_'+k+' is not set' if v=='n' else 'CONFIG_'+k+'='+v)
p.write_text('\n'.join(rows)+'\n')
PY
make -C "$source_dir" O="$objects" CROSS_COMPILE=aarch64-linux-gnu- CC=aarch64-linux-gnu-gcc-12 olddefconfig
make -C "$source_dir" O="$objects" CROSS_COMPILE=aarch64-linux-gnu- CC=aarch64-linux-gnu-gcc-12 \
    BL31="$bl31" -j"${BUILD_JOBS:-16}"
[[ -s "$objects/u-boot-rockchip.bin" ]]
cp "$objects/u-boot-rockchip.bin" "$output/"
cp "$objects/.config" "$output/u-boot.config"
cp "$bl31" "$output/"
printf '%s\n' 'f919c3a889f0ec7d63a48b5d0ed064386b0980bd' > "$output/u-boot-source-commit.txt"
