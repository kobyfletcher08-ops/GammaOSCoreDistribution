#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
stage=$(realpath -- "${1:?stage directory}")
mkdir -p "$stage/output"
exec > >(tee "$stage/output/input-inspection.log") 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 ca-certificates mtools e2fsprogs p7zip-full
python3 "$stage/inspect.py" "$stage"
