#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
source_dir=$(realpath -- "$1")
report=$(realpath -m -- "$2")
mkdir -p "$(dirname -- "$report")"
exec > >(tee "$report") 2>&1
compiler="$source_dir/prebuilts/clang/host/linux-x86/clang-3289846/bin"
for tool in clang llvm-as llvm-link; do
    echo "Checking RenderScript host tool: $tool"
    "$compiler/$tool" --version
done
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cat > "$work/probe.ll" <<'IR'
define i32 @r36h_build_probe() {
    ret i32 0
}
IR
"$compiler/llvm-as" "$work/probe.ll" -o "$work/probe.bc"
"$compiler/llvm-link" "$work/probe.bc" -o "$work/linked.bc"
printf '%s\n' 'int r36h_build_probe(void) { return 0; }' > "$work/probe.c"
for bits in 32 64; do
    if [[ "$bits" == 32 ]]; then target=renderscript32-linux-androideabi; else target=renderscript64-linux-android; fi
    "$compiler/clang" -target "$target" -std=c99 -x renderscript -emit-llvm -c \
        "$work/probe.c" -o "$work/probe-$bits.bc"
    [[ -s "$work/probe-$bits.bc" ]]
done
echo 'RenderScript compiler, assembler, linker and both target bitcode checks passed.'
