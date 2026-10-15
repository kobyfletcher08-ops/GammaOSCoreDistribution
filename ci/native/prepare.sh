#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
stage=$(realpath -- "$1")
mkdir -p "$stage/output"
exec > >(tee "$stage/output/prepare.log") 2>&1
export DEBIAN_FRONTEND=noninteractive GIT_TERMINAL_PROMPT=0 GIT_LFS_SKIP_SMUDGE=1
cache=/var/cache/gammaos-r36h-native
source_dir=$cache/android
source_commit=f1e56c11abc2dd6ec252bda8b320f025165fcbf0
mkdir -p "$cache"
exec 9>"$cache/build.lock"
flock -n 9 || { echo 'Another native GammaOS job owns the source cache.'; exit 1; }
uname -a
df -h "$cache"
free -h
available=$(df -PB1 "$cache" | awk 'NR==2 {print $4}')
if ((available < 120 * 1024 * 1024 * 1024)); then
    echo 'At least 120 GiB free is needed to prepare this source tree.'
    exit 1
fi
apt-get update
apt-get install -y --no-install-recommends git git-lfs ca-certificates curl python3 \
    rsync zip unzip xz-utils file build-essential bc bison flex libssl-dev libelf-dev \
    zlib1g-dev libncurses-dev libxml2-utils xsltproc g++-multilib gcc-multilib \
    lib32z1-dev fontconfig lz4 lzop squashfs-tools cpio dosfstools mtools e2fsprogs \
    gdisk device-tree-compiler u-boot-tools gcc-aarch64-linux-gnu
git lfs version
if [[ ! -d "$source_dir/.git" ]]; then
    mkdir -p "$source_dir"
    git -C "$source_dir" init
    git -C "$source_dir" remote add origin https://github.com/kobyfletcher08-ops/GammaOSCoreDistribution.git
    git -C "$source_dir" config remote.origin.promisor true
    git -C "$source_dir" config remote.origin.partialclonefilter blob:none
fi
[[ $(git -C "$source_dir" remote get-url origin) == https://github.com/kobyfletcher08-ops/GammaOSCoreDistribution.git ]]
git -C "$source_dir" config core.autocrlf false
git -C "$source_dir" config core.symlinks true
git -C "$source_dir" config core.filemode true
git -C "$source_dir" config core.sparseCheckout true
git -C "$source_dir" config core.sparseCheckoutCone false
cat > "$source_dir/.git/info/sparse-checkout" <<'PATTERNS'
/*
!/.repo/
!/out/
!/**/darwin*/
!/**/windows*/
PATTERNS
if ! git -C "$source_dir" cat-file -e "$source_commit^{commit}" 2>/dev/null; then
    git -C "$source_dir" -c protocol.version=2 fetch --no-tags --depth=1 --filter=blob:none origin "$source_commit"
fi
git -C "$source_dir" checkout --detach "$source_commit"
[[ -f "$source_dir/build/envsetup.sh" && -f "$source_dir/build/soong/soong_ui.bash" ]]
# Never restore committed repo metadata or old build outputs. Only hydrate files
# selected into this Linux source worktree; include/exclude prevents fetching
# the many LFS-backed .repo packfiles tracked by this repository.
git -C "$source_dir" lfs install --local --skip-smudge
git -C "$source_dir" lfs pull \
    --include='prebuilts/**,device/**,external/**,packages/**,art/**,frameworks/**,tools/**,vendor/**' \
    --exclude='.repo/**,out/**,**/darwin*/**,**/windows*/**'
git -C "$source_dir" rev-parse HEAD > "$stage/output/gammaos-source-commit.txt"
du -sh "$source_dir" "$source_dir/.git"
df -h "$cache"
python3 - "$source_dir" "$stage/output/source-report.json" <<'PY'
import json, os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
paths = [
    'build/envsetup.sh', 'build/soong/soong_ui.bash',
    'prebuilts/jdk/jdk11/linux-x86/bin/java',
    'prebuilts/clang/host/linux-x86/clang-r450784d/bin/clang',
    'device/google/atv/products/atv_generic_system.mk',
    'vendor/rockchip/common/gpu/MaliTDVx/lib/arm64/libGLES_mali.so',
]
report = {'source_commit': subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'], text=True).strip(),
          'source_path': str(root), 'full_image_built': False, 'files': {}}
for path in paths:
    p = root / path
    report['files'][path] = {'exists': p.is_file(), 'executable': os.access(p, os.X_OK)}
    if p.is_file():
        with p.open('rb') as f: report['files'][path]['lfs_pointer'] = f.read(80).startswith(b'version https://git-lfs.github.com/spec/v1')
pathlib.Path(sys.argv[2]).write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
PY
echo 'Native GammaOS source preparation complete. This job has not built a flashable image.'
