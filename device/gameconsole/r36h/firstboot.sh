#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Native setup only: no foreign boot image, controller daemon or saved root data.
state=/data/vendor/r36h
mkdir -p "$state"
[ -f "$state/setup.done" ] && exit 0
mkdir /dev/.r36h-setup-lock 2>/dev/null || exit 0
trap 'rmdir /dev/.r36h-setup-lock' EXIT
exec >> "$state/setup.log" 2>&1
echo 'Starting native R36H GammaOS setup'
work=/data/local/tmp/r36h-launcher
mkdir -p "$work"

# Daijisho is provided as split APKs by this pinned GammaOS distribution.
tar -tf /system/etc/daijisho_408.tar.gz > "$work/archive.list" || exit 1
while IFS= read -r member; do
    case "$member" in
        /*|../*|*/../*|*/..) echo 'Invalid launcher archive path'; exit 1 ;;
    esac
done < "$work/archive.list"
tar -xf /system/etc/daijisho_408.tar.gz -C "$work" || exit 1
find "$work" -type f -name '*.apk' | sort > "$work/apks.list"
set --
while IFS= read -r apk; do
    set -- "$@" "$apk"
done < "$work/apks.list"
[ "$#" -gt 0 ] || { echo 'No launcher APKs found'; exit 1; }
pm install-multiple -r "$@" || exit 1
cmd package set-home-activity com.magneticchen.daijishou/.app.HomeActivity || exit 1

for apk in \
    /system/etc/RetroArch_aarch64.apk \
    /system/etc/ppsspp_1.18.1.apk \
    /system/etc/mupen64plusae_3.0.335.apk \
    /system/etc/drastic_r2.6.0.4a.apk \
    /system/etc/flycast-release.apk \
    /system/etc/AuroraStore_4.6.2.apk \
    /system/etc/MiXplorer_v6.64.3-API29_B23090720.apk; do
    [ ! -f "$apk" ] || pm install -r "$apk"
done
settings put system screen_off_timeout 300000
settings put global development_settings_enabled 1
settings put global device_provisioned 1
settings put secure user_setup_complete 1
mkdir -p /sdcard/ROMs /sdcard/RetroArch
rm -rf "$work"
touch "$state/setup.done"
echo 'Native setup complete; emulator content can be configured in each app.'
