#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create a new GPT SD image from native build outputs, without loop mounts."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib

SECTOR = 512
MIB = 1024**2
LINUX_FS = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4')
FAT_FS = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*MIB), b''):
            h.update(chunk)
    return h.hexdigest()


def run(*args, capture=False):
    return subprocess.run([str(x) for x in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)


def ext4(path):
    if not path.is_file() or path.stat().st_size < 2048:
        raise ValueError('Missing filesystem image: '+str(path))
    with path.open('rb') as stream:
        if stream.read(4) == b'\x3a\xff\x26\xed':
            raise ValueError('Expected raw ext4, received Android sparse image: '+path.name)
        stream.seek(1080)
        if stream.read(2) != b'\x53\xef':
            raise ValueError('Not an ext4 filesystem: '+path.name)
    run('e2fsck', '-f', '-n', path)


def require_file(image, path):
    result = run('debugfs', '-R', 'stat '+path, image, capture=True).stdout
    if 'Inode:' not in result or 'File not found' in result:
        raise ValueError('Native filesystem is missing '+path)


def ramdisk_members(path):
    data = path.read_bytes()
    if data.startswith(b'\x1f\x8b'):
        data = gzip.decompress(data)
    elif data.startswith((b'\x02\x21\x4c\x18', b'\x04\x22\x4d\x18')):
        data = subprocess.check_output(['lz4', '-dc', str(path)])
    offset, members = 0, {}
    while offset+110 <= len(data):
        header = data[offset:offset+110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError('Invalid native ramdisk CPIO')
        size = int(header[54:62], 16)
        name_size = int(header[94:102], 16)
        offset += 110
        if name_size < 1 or offset+name_size > len(data) or data[offset+name_size-1] != 0:
            raise ValueError('Truncated native ramdisk name')
        name = data[offset:offset+name_size-1].decode()
        offset = (offset+name_size+3) & ~3
        if name == 'TRAILER!!!':
            return members
        if name.startswith('/') or '..' in Path(name).parts or offset+size > len(data):
            raise ValueError('Invalid native ramdisk member')
        members[name.removeprefix('./')] = data[offset:offset+size]
        offset = (offset+size+3) & ~3
    raise ValueError('Native ramdisk has no CPIO trailer')


def gpt_header(current, backup, last_usable, disk_guid, table_lba, table_crc):
    header = bytearray(struct.pack('<8sIIIIQQQQ16sQIII', b'EFI PART', 0x10000, 92, 0, 0,
                                  current, backup, 34, last_usable, disk_guid.bytes_le,
                                  table_lba, 128, 128, table_crc))
    struct.pack_into('<I', header, 16, zlib.crc32(header))
    return bytes(header).ljust(SECTOR, b'\0')


def write_gpt(path, partitions, sectors):
    entries = bytearray(128*128)
    for i, part in enumerate(partitions):
        struct.pack_into('<16s16sQQQ72s', entries, i*128, part['type'].bytes_le,
                         part['guid'].bytes_le, part['start'], part['end'], 0,
                         part['name'].encode('utf-16le').ljust(72, b'\0'))
    last, table_crc, disk_guid = sectors-1, zlib.crc32(entries), uuid.uuid4()
    mbr = bytearray(SECTOR)
    struct.pack_into('<B3sB3sII', mbr, 446, 0, b'\0\x02\0', 0xee, b'\xff'*3, 1, min(last, 0xffffffff))
    mbr[510:512] = b'\x55\xaa'
    with path.open('r+b') as stream:
        for offset, data in ((0, mbr), (SECTOR, gpt_header(1, last, last-33, disk_guid, 2, table_crc)),
                             (2*SECTOR, entries), ((last-32)*SECTOR, entries),
                             (last*SECTOR, gpt_header(last, 1, last-33, disk_guid, last-32, table_crc))):
            stream.seek(offset)
            stream.write(data)


def read_gpt(path):
    size = path.stat().st_size
    if size < 68*SECTOR or size % SECTOR:
        raise ValueError('Invalid GPT disk size')
    with path.open('rb') as stream:
        headers = []
        for lba in (1, size//SECTOR-1):
            stream.seek(lba*SECTOR)
            raw = stream.read(SECTOR)
            if raw[:8] != b'EFI PART':
                raise ValueError('Missing GPT header')
            header_size, checksum = struct.unpack_from('<II', raw, 12)
            if not 92 <= header_size <= SECTOR:
                raise ValueError('Invalid GPT header size')
            check = bytearray(raw[:header_size]); check[16:20] = b'\0'*4
            if zlib.crc32(check) != checksum:
                raise ValueError('GPT header CRC mismatch')
            own, backup, first, last = struct.unpack_from('<4Q', raw, 24)
            table_lba, count, entry_size, table_crc = struct.unpack_from('<QIII', raw, 72)
            if own != lba or backup != (size//SECTOR-1 if lba == 1 else 1) or count != 128 or entry_size != 128:
                raise ValueError('Invalid GPT geometry')
            if table_lba != (2 if lba == 1 else size//SECTOR-33) or first != 34 or last != size//SECTOR-34:
                raise ValueError('Invalid GPT table placement')
            stream.seek(table_lba*SECTOR)
            table = stream.read(count*entry_size)
            if zlib.crc32(table) != table_crc:
                raise ValueError('GPT table CRC mismatch')
            headers.append((raw[56:72], first, last, table))
        if headers[0] != headers[1]:
            raise ValueError('Primary and backup GPT differ')
    result, occupied = [], []
    for off in range(0, len(headers[0][3]), 128):
        row = headers[0][3][off:off+128]
        if row[:16] == b'\0'*16:
            continue
        start, end = struct.unpack_from('<QQ', row, 32)
        if start < headers[0][1] or end > headers[0][2] or start > end:
            raise ValueError('GPT partition outside usable disk')
        if any(start <= other_end and other_start <= end for other_start, other_end in occupied):
            raise ValueError('Overlapping GPT partitions')
        occupied.append((start, end))
        result.append({'name': row[56:128].decode('utf-16le').rstrip('\0'), 'start': start, 'end': end})
    return result


def copy_range(source, image, offset, capacity):
    if source.stat().st_size > capacity:
        raise ValueError('Image does not fit its allocated partition: '+source.name)
    with source.open('rb') as src, image.open('r+b') as target:
        target.seek(offset)
        shutil.copyfileobj(src, target, 4*MIB)


def assemble(kernel, bootloader, android, output):
    output.mkdir(parents=True, exist_ok=True)
    system, vendor, userdata = (android/(name+'.img') for name in ('system', 'vendor', 'userdata'))
    for path in (system, vendor, userdata):
        ext4(path)
    # Android 13 build_image.py wraps system/ together with root_dir even
    # when boot.img contains the first-stage ramdisk.
    for path in ('/system/bin/init', '/system/build.prop'):
        require_file(system, path)
    for path in ('/etc/fstab.r36h', '/etc/init/hw/init.r36h.rc', '/etc/vintf/manifest.xml',
                 '/lib64/hw/audio.primary.r36h.so', '/lib64/hw/hwcomposer.drm.so'):
        require_file(vendor, path)
    audit = json.loads((kernel/'kernel-config-audit.json').read_text())
    if audit['wireless_enabled'] or audit['requested_mismatches']:
        raise ValueError('Kernel configuration audit failed')
    with (kernel/'Image').open('rb') as stream:
        if stream.read(64)[56:60] != b'ARM\x64':
            raise ValueError('Missing ARM64 kernel Image')
    ramdisk = android/'ramdisk.img'
    members = ramdisk_members(ramdisk)
    if 'init' not in members or 'first_stage_ramdisk/fstab.r36h' not in members:
        raise ValueError('Native first-stage init/fstab missing from ramdisk')
    if members['init'][:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', members['init'], 18)[0] != 183:
        raise ValueError('Native ramdisk init must be an ARM64 first-stage executable')
    loader = bootloader/'u-boot-rockchip.bin'
    if not loader.is_file() or not 32768 <= loader.stat().st_size <= 16*MIB-32768:
        raise ValueError('Unexpected native bootloader size')
    with tempfile.TemporaryDirectory(prefix='r36h-image-', dir=output) as directory:
        work = Path(directory)
        initrd = work/'uInitrd'
        compression = 'gzip' if ramdisk.read_bytes()[:2] == b'\x1f\x8b' else 'none'
        run('mkimage', '-A', 'arm64', '-O', 'linux', '-T', 'ramdisk', '-C', compression,
            '-n', 'GammaOS R36H native initramfs', '-d', ramdisk, initrd)
        fat = work/'boot.fat'
        with fat.open('wb') as stream:
            stream.truncate(128*MIB)
        run('mkfs.vfat', '-F', '32', '-n', 'BOOT', fat)
        run('mmd', '-i', fat, '::/extlinux')
        for path in (kernel/'Image', kernel/'rk3326-r36h-v20.dtb', kernel/'rk3326-r36h-v21.dtb', initrd):
            run('mcopy', '-i', fat, path, '::/'+path.name)
        bootargs = ('console=ttyFIQ0 init=/init rootwait androidboot.hardware=r36h '
                    'androidboot.boot_devices=ff370000.dwmmc,ff370000.mmc '
                    'androidboot.selinux=permissive androidboot.verifiedbootstate=orange '
                    'androidboot.force_normal_boot=1')
        config = ['DEFAULT r36h-v21', 'TIMEOUT 30', 'MENU TITLE GammaOS R36H experimental']
        for profile in ('v21', 'v20'):
            config.extend(['LABEL r36h-'+profile, '  MENU LABEL R36H '+profile.upper()+' reference (untested)',
                           '  LINUX /Image', '  INITRD /uInitrd',
                           '  FDT /rk3326-r36h-'+profile+'.dtb', '  APPEND '+bootargs])
        (work/'extlinux.conf').write_text('\n'.join(config)+'\n')
        run('mcopy', '-i', fat, work/'extlinux.conf', '::/extlinux/extlinux.conf')
        (work/'README.txt').write_text('Experimental native GammaOS R36H port. Hardware boot is untested.\n'
                                      'Default: public R36H V21 reference. For V20 change DEFAULT in extlinux/extlinux.conf.\n'
                                      'Android userdebug with permissive SELinux. Userdata is fixed at 8 GiB.\n'
                                      'Flash to a spare microSD card of at least 16 GB.\n')
        run('mcopy', '-i', fat, work/'README.txt', '::/README.txt')
        partitions, start = [], 16*MIB//SECTOR
        for name, source, kind in (('BOOT', fat, FAT_FS), ('system', system, LINUX_FS),
                                   ('vendor', vendor, LINUX_FS), ('userdata', userdata, LINUX_FS)):
            length = ((source.stat().st_size+4*MIB-1)//(4*MIB))*(4*MIB)//SECTOR
            partitions.append({'name': name, 'start': start, 'end': start+length-1,
                               'guid': uuid.uuid4(), 'type': kind, 'source': source})
            start += length
        sectors = start+2048
        image = output/'GammaOS-Core-R36H-NATIVE-EXPERIMENTAL.img'
        partial = image.with_suffix('.img.partial')
        with partial.open('wb') as stream:
            stream.truncate(sectors*SECTOR)
        write_gpt(partial, partitions, sectors)
        copy_range(loader, partial, 64*SECTOR, 16*MIB-64*SECTOR)
        for part in partitions:
            copy_range(part['source'], partial, part['start']*SECTOR,
                       (part['end']-part['start']+1)*SECTOR)
        parsed = read_gpt(partial)
        if [p['name'] for p in parsed] != ['BOOT', 'system', 'vendor', 'userdata']:
            raise ValueError('Unexpected final partition layout')
        run('sgdisk', '-v', partial)
        os.replace(partial, image)
    report = {'full_image_built': True, 'native_build': True, 'hardware_boot_tested': False,
              'default_reference_profile': 'R36H V21', 'partitions': parsed,
              'image_sha256': digest(image),
              'sources': json.loads((kernel/'SOURCES.json').read_text())}
    (output/'build-manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    run('xz', '-T', '4', '-1', image)
    archive = image.with_suffix('.img.xz')
    (output/'SHA256SUMS').write_text(digest(archive)+'  '+archive.name+'\n'+
                                    digest(output/'build-manifest.json')+'  build-manifest.json\n')
    print('Native full SD image assembled and structurally verified:', archive, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--bootloader', type=Path, required=True)
    parser.add_argument('--android', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assemble(args.kernel, args.bootloader, args.android, args.output)
