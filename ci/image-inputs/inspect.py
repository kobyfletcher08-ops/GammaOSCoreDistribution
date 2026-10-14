#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect official firmware inputs before attempting an experimental port."""
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path

stage = Path(sys.argv[1])
config = json.loads((stage / "sources.json").read_text())
cache = Path("/var/cache/gammaos-r36h-image-inputs")
cache.mkdir(parents=True, exist_ok=True)
output = stage / "output"
output.mkdir(parents=True, exist_ok=True)


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def download(url, path, expected=None):
    if path.exists() and (expected is None or sha256(path) == expected):
        return sha256(path)
    part = path.with_suffix(path.suffix + ".partial")
    part.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "GammaOS-R36H-image-builder"})
    with urllib.request.urlopen(request, timeout=180) as response, part.open("wb") as writer:
        shutil.copyfileobj(response, writer, 4 * 1024 * 1024)
    digest = sha256(part)
    if expected and digest != expected:
        part.unlink()
        raise ValueError("Official base download checksum mismatch")
    part.replace(path)
    return digest


archive_path = cache / "andr36oid-r36s-20260316.zip"
print("Downloading the checksum-pinned public AndR36oid SD image", flush=True)
download(config["base_url"], archive_path, config["base_sha256"])
base = cache / "andr36oid-r36s-20260316.img"
if not base.exists():
    with zipfile.ZipFile(archive_path) as archive:
        images = [item for item in archive.infolist()
                  if not item.is_dir() and item.filename.lower().endswith(".img")]
        if len(images) != 1:
            raise ValueError("Expected one SD image in the official archive")
        part = base.with_suffix(".partial")
        with archive.open(images[0]) as reader, part.open("wb") as writer:
            shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
        part.replace(base)

with base.open("rb") as reader:
    reader.seek(512)
    header = bytearray(reader.read(512))
    if header[:8] != b"EFI PART":
        raise ValueError("The public base does not use GPT")
    header_size, crc = struct.unpack_from("<II", header, 12)
    if not 92 <= header_size <= 512:
        raise ValueError("Invalid GPT header")
    struct.pack_into("<I", header, 16, 0)
    if zlib.crc32(header[:header_size]) != crc:
        raise ValueError("Invalid GPT header CRC")
    entries_lba, count, entry_size, entries_crc = struct.unpack_from("<QIII", header, 72)
    if entry_size < 128 or count * entry_size > 16 * 1024 * 1024:
        raise ValueError("Invalid GPT entry table")
    reader.seek(entries_lba * 512)
    entries = reader.read(count * entry_size)
    if zlib.crc32(entries) != entries_crc:
        raise ValueError("Invalid GPT entry CRC")
    parts = []
    for index in range(count):
        entry = entries[index * entry_size:(index + 1) * entry_size]
        if entry[:16] == bytes(16):
            continue
        first, last = struct.unpack_from("<QQ", entry, 32)
        parts.append({"number": index + 1, "name": entry[56:128].decode("utf-16-le").split("\0", 1)[0],
                      "offset": first * 512, "size": (last - first + 1) * 512})

report = {"base_url": config["base_url"], "base_download_sha256": config["base_sha256"],
          "base_image_bytes": base.stat().st_size, "partitions": parts,
          "hardware_boot_tested": False, "ready_for_assembly": False}
names = {part["name"].lower(): part for part in parts}
print(json.dumps(report, indent=2), flush=True)
if "boot" in names:
    boot = names["boot"]
    command = ["mtype", "-i", f"{base}@@{boot['offset']}", "::boot.ini"]
    result = subprocess.run(command, text=True, capture_output=True)
    (output / "base-boot.ini.txt").write_text(result.stdout + result.stderr)
    report["first_stage_ramdisk_boot"] = "ramdisk.uimg" in result.stdout and "booti" in result.stdout
if "vendor" not in names:
    report["blocker"] = "Public AndR36oid image has no separate vendor partition; it cannot be used with the GammaOS GSI packager."
else:
    vendor = names["vendor"]
    vendor_file = cache / "vendor-inspection.img"
    with base.open("rb") as reader, vendor_file.open("wb") as writer:
        reader.seek(vendor["offset"])
        remaining = vendor["size"]
        while remaining:
            block = reader.read(min(remaining, 4 * 1024 * 1024))
            if not block:
                raise ValueError("Truncated vendor partition")
            writer.write(block)
            remaining -= len(block)
    result = subprocess.run(["debugfs", "-R", "cat /etc/vintf/manifest.xml", str(vendor_file)],
                            text=True, capture_output=True)
    (output / "vendor-manifest.xml").write_text(result.stdout)
    report["vendor_manifest_present"] = "<manifest" in result.stdout
    report["ready_for_assembly"] = bool(report.get("first_stage_ramdisk_boot") and report["vendor_manifest_present"])
    if not report["ready_for_assembly"]:
        report["blocker"] = "Public image lacks the required first-stage ramdisk or vendor VINTF manifest."

# Record the exact blocker before stopping; do not publish an invalid SD image.
(output / "image-input-report.json").write_text(json.dumps(report, indent=2) + "\n")
if not report["ready_for_assembly"]:
    raise SystemExit(report["blocker"])

gamma = cache / "GammaOS_Core_Beta3_RG_353.7z"
print("Downloading official GammaOS Core Beta 3 for system-image inspection", flush=True)
report["gamma_archive_sha256"] = download(config["gamma_url"], gamma)
listing = subprocess.run(["7z", "l", "-slt", "-p" + config["gamma_password"], str(gamma)],
                         text=True, capture_output=True, check=True).stdout
(output / "gamma-archive-listing.txt").write_text(listing)
report["gamma_archive_url"] = config["gamma_url"]
(output / "image-input-report.json").write_text(json.dumps(report, indent=2) + "\n")
print("Base layout passed. GammaOS archive inventory saved for assembly.", flush=True)
