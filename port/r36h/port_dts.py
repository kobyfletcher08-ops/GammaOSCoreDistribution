#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Port board wiring from a pinned public R36H DTB to Rockchip 5.10.

The SoC register map, clocks and driver nodes come from the new kernel. Only
board wiring, regulators, panel commands and input mappings come from the DTB.
This does not establish that the reference board matches the user's hardware.
"""
import argparse
import json
import re
from pathlib import Path
from fdt import cells, read, string

ROOTS = ('/vccsys', '/backlight', '/rk817-sound', '/odroidgo3-keys', '/odroidgo3-joypad')
CHILDREN = {'i2c0': ('/i2c@ff180000/pmic@20',),
            'dsi': ('/dsi@ff450000/panel@0',),
            'pinctrl': ('/pinctrl/pmic', '/pinctrl/btns')}
# Properties describing board wiring. Never copy a 4.4 SoC register map,
# clocks, interrupt table, DMA channel, or power-domain index into 5.10.
OVERRIDES = {
    'cpu0': ('cpu-supply',), 'bus_apll': ('status', 'bus-supply'),
    'pmu_io_domains': ('status', 'pmuio1-supply', 'pmuio2-supply'),
    'io_domains': ('status',)+tuple('vccio%d-supply' % i for i in range(1, 7)),
    'i2c0': ('status', 'clock-frequency', 'i2c-scl-rising-time-ns', 'i2c-scl-falling-time-ns'),
    'i2s1_2ch': ('status', 'rockchip,playback-channels', 'rockchip,capture-channels'),
    'sdmmc': ('status', 'bus-width', 'cap-sd-highspeed', 'cap-mmc-highspeed', 'cd-gpios',
              'sd-uhs-sdr12', 'sd-uhs-sdr25', 'sd-uhs-sdr50', 'vmmc-supply', 'vqmmc-supply'),
    'sdio': ('status', 'bus-width', 'cap-sd-highspeed', 'cd-gpios', 'vmmc-supply', 'vqmmc-supply'),
    'saradc': ('status', 'vref-supply'), 'tsadc': ('status',),
    'dsi': ('status',), 'dsi_in_vopb': ('status',), 'video_phy': ('status',),
    'vopb': ('status',), 'vopb_mmu': ('status',),
    'route_dsi': ('status', 'connect'), 'display_subsystem': ('status',),
    'u2phy': ('status',), 'u2phy_host': ('status',),
    'usb_host0_ehci': ('status',), 'usb_host0_ohci': ('status',),
    'gpu': ('status', 'mali-supply'),
}
STRINGS = {'compatible', 'model', 'status', 'label', 'function', 'pins',
           'regulator-name', 'regulator-compatible', 'dr_mode', 'joypad-name',
           'simple-audio-card,format', 'simple-audio-card,name'}
REFS = {'pinctrl-0', 'pinctrl-1', 'pinctrl-2', 'pinctrl-3', 'native-mode',
        'sound-dai', 'interrupt-parent', 'remote-endpoint', 'backlight',
        'extcon', 'connect', 'clocks', 'assigned-clocks', 'assigned-clock-parents',
        'io-channels', 'pwms'}


def generate(reference, output, profile):
    nodes = read(reference)
    model = string(nodes['/'].properties['model'])
    expected = {'v20': 'HL-R36H-V20 2024-05-18', 'v21': 'HL-R36H-V21 2024-11-18'}
    if model != expected[profile]:
        raise ValueError('R36H reference model mismatch: '+model)
    symbols = {name: string(path) for name, path in nodes['/__symbols__'].properties.items()}
    labels = {}
    for name, path in symbols.items():
        labels.setdefault(path, name)
    handles = {cells(n.properties['phandle'])[0]: labels.get(path)
               for path, n in nodes.items() if 'phandle' in n.properties}
    selected = set()
    for root in ROOTS + tuple(p for group in CHILDREN.values() for p in group):
        selected.update(p for p in nodes if p == root or p.startswith(root+'/'))
    for path in selected:
        if 'phandle' in nodes[path].properties and not labels.get(path):
            labels[path] = 'r36h_' + re.sub('[^a-zA-Z0-9_]', '_', path)
            handles[cells(nodes[path].properties['phandle'])[0]] = labels[path]

    def property_line(name, value):
        if name in ('phandle', 'linux,phandle'):
            return None
        if not value:
            return name+';'
        if name in STRINGS or name.endswith('-names') or name.endswith(',widgets') or name.endswith(',routing'):
            return name+' = '+', '.join(json.dumps(v) for v in string(value).split('\0'))+';'
        if 'sequence' in name:
            return name+' = ['+' '.join('%02x' % b for b in value)+'];'
        words = cells(value)
        refs = set()
        if name.endswith('-supply') or name in ('interrupt-parent', 'native-mode', 'remote-endpoint', 'backlight', 'connect'):
            refs = {0}
        elif name.startswith('pinctrl-') and name != 'pinctrl-names':
            refs = set(range(len(words)))
        elif name == 'rockchip,pins':
            refs = set(range(3, len(words), 4))
        elif name.endswith('gpios') or name.endswith('gpio') or name in REFS:
            # The copied board subtrees use one provider per property, except
            # clocks (provider, clock id) and sound widget string properties.
            refs = set(range(0, len(words), 2)) if name in ('clocks', 'assigned-clocks', 'assigned-clock-parents') else {0}
        result = []
        for i, word in enumerate(words):
            if i in refs:
                label = handles.get(word)
                if not label:
                    raise ValueError('Unresolved board reference in '+name+': '+hex(word))
                result.append('&'+label)
            else:
                result.append(hex(word))
        return name+' = <'+' '.join(result)+'>;'

    def subtree(path, depth=1):
        n = nodes[path]
        label = labels.get(path)
        out = ['\t'*depth+(label+': ' if label else '')+n.name+' {']
        for name, value in n.properties.items():
            if path == '/odroidgo3-joypad' and (name in ('pwms', 'pwm-names') or name.startswith('rumble-')):
                continue
            if path == '/odroidgo3-joypad' and name == 'compatible':
                value = b'gammaos,r36h-joypad\0'
            if path == '/odroidgo3-joypad' and name == 'joypad-name':
                value = b'R36H Gamepad\0'
            if path == '/dsi@ff450000/panel@0' and name == 'compatible':
                value = b'simple-panel-dsi\0'
            # The public V20 DTB's native-mode references stale phandle 0xa0;
            # its timing0 symbol points to the actual preferred timing node.
            if path.endswith('/panel@0/display-timings') and name == 'native-mode':
                out.append('\t'*(depth+1)+'native-mode = <&timing0>;')
                continue
            line = property_line(name, value)
            if line:
                out.append('\t'*(depth+1)+line)
        for child in n.children:
            out.extend(subtree(child.path, depth+1))
        out.append('\t'*depth+'};')
        return out

    out = ['// SPDX-License-Identifier: GPL-2.0-only',
           '// Board data: southoz/dArkOSRE-R36; see SOURCES.json.',
           '// EXPERIMENTAL: reference wiring, physical boot untested.',
           '/dts-v1/;', '#include "rk3326.dtsi"', '#include "px30-android.dtsi"',
           '/ {', '\tmodel = '+json.dumps('GammaOS '+model)+';',
           '\tcompatible = "gameconsole,r36h-'+profile+'", "rockchip,rk3326";']
    for path in ROOTS:
        if path in nodes:
            out.extend(subtree(path))
    out.extend(['};', ''])
    for label in dict.fromkeys((*OVERRIDES, *CHILDREN)):
        path = symbols.get(label)
        if not path:
            continue
        out.append('&'+label+' {')
        for name in OVERRIDES.get(label, ()):
            if name in nodes[path].properties:
                line = property_line(name, nodes[path].properties[name])
                if line:
                    out.append('\t'+line)
        for child in CHILDREN.get(label, ()):
            if child in nodes:
                out.extend(subtree(child))
        if label in ('sdmmc', 'sdio'):
            out.append('\tmax-frequency = <50000000>;')
        out.extend(['};', ''])
    # Enable the PHY used by DWC2. The stock reference has this PHY disabled
    # despite enabling the controller, which prevents reliable host tethering.
    # Disable unrelated radio/eMMC/DDR scaling nodes on this SD-only target.
    out.extend(['&u2phy_otg { status = "okay"; phy-supply = <&otg_switch>; };',
                '&usb20_otg { status = "okay"; dr_mode = "otg"; };',
                '&emmc { status = "disabled"; };',
                '&gmac { status = "disabled"; };',
                '&dmc { status = "disabled"; };',
                '&pwm1 { status = "okay"; };',
                '&chosen { bootargs = "console=ttyFIQ0 init=/init rootwait"; };'])
    Path(output).write_text('\n'.join(out)+'\n')
    return {'profile': profile, 'reference_model': model, 'hardware_boot_tested': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--profile', choices=('v20', 'v21'), required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.reference, args.output, args.profile), indent=2))
