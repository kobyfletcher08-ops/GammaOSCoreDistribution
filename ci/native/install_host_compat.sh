#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# RenderScript's pinned clang-3289846 needs the real ncurses/terminfo ABI 5.
set -euo pipefail
compat_dir=$(realpath -m -- "$1")
[[ $(dpkg --print-architecture) == amd64 ]] || {
    echo 'The native Android build requires an amd64 Linux host.' >&2
    exit 1
}
all_installed=true
for package in libtinfo5 libncurses5; do
    status=$(dpkg-query -W -f='${db:Status-Status}' "$package:amd64" 2>/dev/null || true)
    if [[ "$status" != installed ]]; then all_installed=false; fi
done
if [[ "$all_installed" == true ]]; then
    echo 'Legacy ncurses/terminfo host packages are already installed.'
    exit 0
fi
mkdir -p "$compat_dir"
version=6.3-2ubuntu0.3
# SHA-256 values published on packages.ubuntu.com/jammy/amd64/{package}/download.
fetch_package() {
    local package=$1 expected=$2
    local name="${package}_${version}_amd64.deb" origin
    local path="$compat_dir/${package}_${version}_amd64.deb"
    if [[ -f "$path" ]] && printf '%s  %s\n' "$expected" "$path" | sha256sum --check --status; then
        return
    fi
    for origin in https://security.ubuntu.com/ubuntu https://archive.ubuntu.com/ubuntu; do
        if curl --proto '=https' --proto-redir '=https' --fail --silent --show-error --location \
            --retry 3 --connect-timeout 20 --max-time 180 \
            "$origin/pool/universe/n/ncurses/$name" -o "$path.part"; then
            if printf '%s  %s\n' "$expected" "$path.part" | sha256sum --check --status; then
                mv -f -- "$path.part" "$path"
                return
            fi
        fi
    done
    echo "Cannot obtain checksum-verified Ubuntu package: $name" >&2
    return 1
}
fetch_package libtinfo5 4df4288404108f1a156d014e8764a064e977e34e6d44931ab60451694c03c90d
fetch_package libncurses5 58da01991712c6856af0658dc5e9cb533c1a6854ab950055ade185e35bc9c276
for package in libtinfo5 libncurses5; do
    deb="$compat_dir/${package}_${version}_amd64.deb"
    [[ $(dpkg-deb -f "$deb" Package) == "$package" ]]
    [[ $(dpkg-deb -f "$deb" Version) == "$version" ]]
    [[ $(dpkg-deb -f "$deb" Architecture) == amd64 ]]
done
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends \
    "$compat_dir/libtinfo5_${version}_amd64.deb" "$compat_dir/libncurses5_${version}_amd64.deb"
dpkg-query -W -f='${binary:Package} ${Version}\n' libtinfo5:amd64 libncurses5:amd64
