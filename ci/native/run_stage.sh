#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
stage=$(realpath -- "$1")
phase=$2
support=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cache=/var/cache/gammaos-r36h-native
mkdir -p "$stage/output" "$cache/artifacts"
exec > >(tee "$stage/output/$phase.log") 2>&1
exec 9>"$cache/build.lock"
flock -n 9 || { echo 'Another native job owns the build cache.'; exit 1; }
case "$phase" in
    kernel)
        export BUILD_JOBS=${BUILD_JOBS:-16}
        apt-get install -y --no-install-recommends python3-pyelftools flex bison bc python3-dev swig libgnutls28-dev
        bash "$support/port/r36h/build_kernel.sh" "$cache" "$cache/artifacts/kernel"
        cp -a "$cache/artifacts/kernel" "$stage/output/"
        bash "$support/port/r36h/build_bootloader.sh" "$cache" "$cache/artifacts/bootloader"
        cp -a "$cache/artifacts/bootloader" "$stage/output/"
        ;;
    android)
        bash "$support/ci/native/build_android.sh" "$stage/output/android"
        ;;
    image)
        product_out=$(cat "$cache/android-product-out.txt")
        [[ "$product_out" == "$cache/out-native/target/product/r36h" ]]
        python3 -u "$support/port/r36h/package_native.py" --kernel "$cache/artifacts/kernel" \
            --bootloader "$cache/artifacts/bootloader" --android "$product_out" --output "$stage/output/image"
        ;;
    *) echo 'Unknown native build stage' >&2; exit 2 ;;
esac
