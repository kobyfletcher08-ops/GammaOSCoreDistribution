#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
stage=$(realpath -- "${1:?stage directory required}")
task=${2:?task required}
case "$task" in checks|kernel|image) ;; *) echo 'Unknown task' >&2; exit 2 ;; esac
output="$stage/output/$task"
mkdir -p "$output"
exec > >(tee -a "$output/build.log") 2>&1
[[ $(uname -m) == x86_64 ]] || { echo 'An x86_64 Linux environment is required.' >&2; exit 1; }
[[ $(id -u) == 0 ]] || { echo 'Run this task as Linux root.' >&2; exit 1; }
# Source and objects stay on Linux storage to preserve symlinks and file names.
work=$(mktemp -d /tmp/r36h-build.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
cd "$work"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 ca-certificates
python3 - "$stage" "$task" <<'PY'
import hashlib, json, re, shutil, sys, zipfile
from pathlib import Path, PurePosixPath
stage, task = Path(sys.argv[1]), sys.argv[2]
config = json.loads((stage / "inputs.json").read_text())
assert config["mode"] in ("kernel", "assemble"), "Invalid build mode"
assert config["panel"] in ("keep", "0", "1", "2", "3", "4", "5", "6"), "Invalid panel"
assert 1 <= config["build_jobs"] <= 64, "Invalid job count"
if config["mode"] == "assemble":
    for prefix in ("base", "system"):
        assert (config[prefix + "_url"] or "").startswith("https://"), prefix + " needs a public HTTPS URL"
        assert re.fullmatch(r"[0-9a-fA-F]{64}", config[prefix + "_sha256"] or ""), prefix + " needs the download SHA-256"
archive_path = stage / "input/r36h-build-support.zip"
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == config["support_sha256"].lower(), "Support checksum mismatch"
with zipfile.ZipFile(archive_path) as archive:
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        assert not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename, "Invalid support path"
        assert item.external_attr >> 16 & 0o170000 != 0o120000, "Support symlinks are not allowed"
    archive.extractall(".")
if task == "checks":
    shutil.copyfile(archive_path, stage / "output/checks/r36h-build-support.zip")
PY
case "$task" in
  checks)
    bash port/r36h/install_tools.sh checks
    shellcheck -s bash port/r36h/*.sh
    shellcheck -s sh device/gameconsole/r36h/r36h-netdiag.sh
    python3 -m unittest discover -s port/r36h/tests -v
    ;;
  kernel)
    available_kb=$(df -Pk "$work" | awk 'NR==2 {print $4}')
    ((available_kb >= 10 * 1024 * 1024)) || {
      echo 'At least 10 GiB free on the Linux filesystem is required for the kernel build.' >&2; exit 1;
    }
    apt-get install -y --no-install-recommends git
    bash port/r36h/install_tools.sh kernel
    pinned_commit=25012887350da79f28cb6c73d04814abcc58578f
    git init _kernel
    git -C _kernel config core.autocrlf false
    git -C _kernel remote add origin https://github.com/andr36oid/android_kernel_gameconsole_r36s.git
    git -C _kernel fetch --depth=1 origin "$pinned_commit"
    git -C _kernel checkout --detach FETCH_HEAD
    [[ $(git -C _kernel rev-parse HEAD) == "$pinned_commit" ]]
    BUILD_JOBS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build_jobs"])' "$stage/inputs.json")
    export BUILD_JOBS
    bash port/r36h/build_kernel.sh _kernel "$work/objects" "$output"
    (cd "$output" && sha256sum -c SHA256SUMS)
    ;;
  image)
    bash port/r36h/install_tools.sh image
    mkdir -p artifacts/kernel images
    cp -a "$stage/input/kernel/." artifacts/kernel/
    (cd artifacts/kernel && sha256sum -c SHA256SUMS)
    [[ $(cat artifacts/kernel/kernel-source-commit.txt) == 25012887350da79f28cb6c73d04814abcc58578f ]]
    python3 - "$stage" "$output" <<'PY'
import json, subprocess, sys
from pathlib import Path
stage, output = Path(sys.argv[1]), Path(sys.argv[2])
config = json.loads((stage / "inputs.json").read_text())
assert config["mode"] == "assemble", "Image task requires assemble mode"
for name in ("base", "system"):
    subprocess.run([sys.executable, "port/r36h/prepare_input.py", "--url", config[name + "_url"],
                    "--sha256", config[name + "_sha256"], "--output", f"images/{name}.img"], check=True)
subprocess.run([sys.executable, "port/r36h/package_image.py", "--base", "images/base.img",
                "--system", "images/system.img", "--kernel", "artifacts/kernel", "--panel", config["panel"],
                "--output", str(output / "GammaOS-Core-R36H-EXPERIMENTAL.img")], check=True)
PY
    xz -T4 -1 "$output/GammaOS-Core-R36H-EXPERIMENTAL.img"
    cp port/r36h/README.md "$output/README.md"
    checksum_file=$(mktemp)
    (cd "$output" && find . -type f ! -name SHA256SUMS ! -name build.log -print0 |
      sort -z | xargs -0 sha256sum > "$checksum_file")
    mv -- "$checksum_file" "$output/SHA256SUMS"
    ;;
esac
