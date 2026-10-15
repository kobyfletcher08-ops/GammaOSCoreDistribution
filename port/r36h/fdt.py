#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read a flattened device tree without executing firmware or external tools."""
from dataclasses import dataclass, field
from pathlib import Path
import struct


@dataclass
class Node:
    name: str
    path: str
    properties: dict[str, bytes] = field(default_factory=dict)
    children: list['Node'] = field(default_factory=list)


def cells(value):
    if len(value) % 4:
        raise ValueError('Device-tree cell property is not word aligned')
    return list(struct.unpack('>' + 'I' * (len(value) // 4), value))


def string(value):
    if not value.endswith(b'\0'):
        raise ValueError('Device-tree string is not terminated')
    return value[:-1].decode('ascii')


def read(path):
    data = Path(path).read_bytes()
    if len(data) < 40:
        raise ValueError('Truncated device-tree header')
    magic, size, structure, strings, reserves, version, compatible, _, strings_size, struct_size = struct.unpack_from('>10I', data)
    if magic != 0xd00dfeed or size != len(data) or version < 17 or compatible > 17:
        raise ValueError('Unsupported or truncated device tree')
    if any(start < 40 or start + length > size for start, length in ((structure, struct_size), (strings, strings_size))):
        raise ValueError('Device-tree block is outside the file')
    if reserves < 40 or reserves + 16 > size:
        raise ValueError('Invalid device-tree reserve block')
    names = data[strings:strings+strings_size]
    offset, end = structure, structure+struct_size
    nodes, stack = {}, []
    while offset + 4 <= end:
        tag = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        if tag == 1:
            stop = data.index(0, offset, end)
            name = data[offset:stop].decode('ascii')
            offset = (stop+4) & ~3
            path = (stack[-1].path.rstrip('/') if stack else '') + '/' + name
            path = path or '/'
            if path in nodes:
                raise ValueError('Duplicate device-tree node: '+path)
            node = Node(name, path)
            if stack:
                stack[-1].children.append(node)
            elif nodes:
                raise ValueError('Multiple device-tree roots')
            nodes[path] = node
            stack.append(node)
        elif tag == 2:
            if not stack:
                raise ValueError('Unbalanced device tree')
            stack.pop()
        elif tag == 3:
            if not stack or offset + 8 > end:
                raise ValueError('Invalid device-tree property')
            length, name_offset = struct.unpack_from('>2I', data, offset)
            offset += 8
            if offset + length > end or name_offset >= len(names):
                raise ValueError('Device-tree property is outside its block')
            stop = names.index(0, name_offset)
            name = names[name_offset:stop].decode('ascii')
            if name in stack[-1].properties:
                raise ValueError('Duplicate device-tree property')
            stack[-1].properties[name] = data[offset:offset+length]
            offset = (offset+length+3) & ~3
        elif tag == 4:
            continue
        elif tag == 9:
            if stack or '/' not in nodes:
                raise ValueError('Unbalanced device tree')
            return nodes
        else:
            raise ValueError('Invalid device-tree structure token')
    raise ValueError('Missing device-tree end token')
