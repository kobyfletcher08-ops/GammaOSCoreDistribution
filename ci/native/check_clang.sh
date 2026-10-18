#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
source_dir=$(realpath -- "$1")
report=$(realpath -m -- "$2")
mkdir -p "$(dirname -- "$report")"
exec > >(tee "$report") 2>&1
compiler="$source_dir/prebuilts/clang/host/linux-x86/clang-r450784d/bin"
release=$(uname -r)
printf 'Checking Android host compiler on kernel %s\n' "$release"
work=$(mktemp -d)
patched=
trap 'rm -rf -- "$work"; if [[ -n "$patched" ]]; then rm -f -- "$patched"; fi' EXIT

# WSL1 rejects the mixed 4 KiB/2 MiB PT_LOAD alignments in this BOLT binary.
# Rewriting its existing interpreter with patchelf normalizes those headers.
# https://github.com/android/ndk/issues/1755
# https://github.com/microsoft/WSL/issues/8681
# Hydration verifies/restores the original LFS object before every preparation.
# Only adapt this known host executable, preserving the Git/LFS cached bytes.
if [[ "${release,,}" == *microsoft* && "${release,,}" != *wsl2* ]]; then
    binary=$(realpath -- "$compiler/clang.real")
    [[ "$binary" == "$compiler/clang-14" ]]
    if "$binary" --version > "$work/clang-before.txt" 2>&1; then
        echo 'Clang already executes on this WSL1 host.'
    else
        cat "$work/clang-before.txt"
        echo 'Applying the documented WSL1 host-compiler ELF workaround.'
        expected=9f53122c3c96342874a38014a8ba3dd3af1be317d109cdc002922429d9e2cf41
        printf '%s  %s\n' "$expected" "$binary" | sha256sum --check --strict
        [[ -x /lib64/ld-linux-x86-64.so.2 ]]
        patched=$(mktemp "$compiler/.clang-14-wsl1.XXXXXX")
        cp --preserve=mode -- "$binary" "$patched"
        patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 "$patched"
        "$patched" --version
        mv -f -- "$patched" "$binary"
        patched=
        sha256sum -- "$binary"
    fi
fi

for tool in clang clang++ clang-tidy ld.lld; do
    echo "Checking Android host tool: $tool"
    "$compiler/$tool" --version
done
cat > "$work/probe.c" <<'C'
unsigned long long r36h_c_probe(const unsigned *values, unsigned count) {
    unsigned long long result = 0;
    for (unsigned i = 0; i < count; ++i) result += values[i] * (i + 1);
    return result;
}
C
cat > "$work/probe.cpp" <<'CPP'
template <typename T> T twice(T value) { return value + value; }
extern "C" int r36h_cpp_probe(int value) { return twice(value); }
CPP
for target in x86_64-linux-gnu armv7a-linux-androideabi aarch64-linux-android; do
    echo "Compiling and linking C/C++ probe for $target"
    "$compiler/clang" --target="$target" -O2 -ffreestanding -fno-stack-protector \
        -c "$work/probe.c" -o "$work/$target-c.o"
    "$compiler/clang++" --target="$target" -O2 -ffreestanding -fno-stack-protector \
        -std=c++17 -fno-exceptions -fno-rtti -c "$work/probe.cpp" -o "$work/$target-cpp.o"
    "$compiler/ld.lld" -r "$work/$target-c.o" "$work/$target-cpp.o" -o "$work/$target-linked.o"
    [[ -s "$work/$target-linked.o" ]]
    file "$work/$target-linked.o"
done
echo 'Android Clang C/C++ and linker checks passed for host, ARM32 and ARM64.'
