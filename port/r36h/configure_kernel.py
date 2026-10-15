#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Apply and audit a Kconfig-resolved wired-only configuration."""
import argparse
import json
import re
from pathlib import Path

LINE = re.compile(r"^(?:CONFIG_(\w+)=(.*)|# CONFIG_(\w+) is not set)$")
DECL = re.compile(r"^\s*(?:menuconfig|config)\s+(\w+)\s*$", re.M)
WIRELESS_ROOTS = (
    "drivers/net/wireless", "net/wireless", "net/mac80211",
    "drivers/bluetooth", "net/bluetooth", "net/rfkill",
    "drivers/net/rfkill",
)

def values(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        match = LINE.match(line)
        if match:
            name = match.group(1) or match.group(3)
            result[name] = match.group(2) if match.group(1) else "n"
    return result

def banned_symbols(source):
    banned = {"WIRELESS", "WLAN", "CFG80211", "MAC80211", "BT", "RFKILL"}
    for relative in WIRELESS_ROOTS:
        folder = Path(source) / relative
        if folder.is_dir():
            for file in folder.rglob("Kconfig*"):
                if file.is_file():
                    banned.update(DECL.findall(file.read_text(errors="replace")))
    return banned

def process(source, config, fragment, audit=False):
    requested = values(fragment)
    banned = banned_symbols(source)
    current = values(config)
    if audit:
        missing = {name: {"expected": value, "actual": current.get(name, "n")}
                   for name, value in requested.items()
                   if current.get(name, "n") != value}
        wireless = {name: current[name] for name in sorted(banned)
                    if current.get(name) in ("y", "m")}
        report = {"requested_mismatches": missing, "wireless_enabled": wireless,
                  "required": requested, "wireless_symbols_checked": len(banned)}
        if missing or wireless:
            raise ValueError(json.dumps(report, indent=2))
        return report
    for name in banned:
        current[name] = "n"
    for name, value in requested.items():
        if name in banned and value != "n":
            raise ValueError("Fragment tries to enable wireless: " + name)
        current[name] = value
    # Keep strings/numerical settings intact; olddefconfig resolves dependencies.
    Path(config).write_text("".join(
        f"# CONFIG_{name} is not set\n" if value == "n" else f"CONFIG_{name}={value}\n"
        for name, value in sorted(current.items())))
    return {"disabled_wireless_symbols": len(banned)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fragment", type=Path, required=True)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(process(args.source, args.config, args.fragment, args.audit), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")

if __name__ == "__main__":
    main()
