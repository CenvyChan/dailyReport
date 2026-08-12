# -*- coding: utf-8 -*-
"""
解除 .xls/.xlsm 里 VBA 工程的 VBE 界面锁（在副本上操作，不改原文件）。

原理：MS-OVBA 2.4.3 里 PROJECT 流的 CMG / DPB / GC 三个值分别是
  CMG = ProjectProtectionState (4 字节)
  DPB = ProjectPassword
  GC  = ProjectVisibilityState (1 字节)
它们用同一套「Data Encryption」做混淆（不是加密，可逆且无密钥依赖：
ProjKey 直接存在密文里）。把 CMG 置 0、DPB 置 0x00、GC 置 0xFF 就是「未保护 + 无口令 + 可见」。

用法:
  python unlock_vba_project.py inspect <file.xls>
  python unlock_vba_project.py unlock  <src.xls> <dst.xls>
"""
import os
import shutil
import struct
import sys

import olefile

PROJECT_PATH = '_VBA_PROJECT_CUR/PROJECT'


def decrypt(hex_str):
    """MS-OVBA 2.4.3.3 Decryption. 返回 (data, proj_key, seed, ignored)。"""
    ed = bytes.fromhex(hex_str)
    seed, version_enc, proj_key_enc = ed[0], ed[1], ed[2]
    version = seed ^ version_enc
    if version != 2:
        raise ValueError(f'Version 应为 2, 实际 {version}')
    proj_key = seed ^ proj_key_enc
    ignored_length = (seed & 6) >> 1

    unencrypted1, encrypted1, encrypted2 = proj_key, proj_key_enc, version_enc
    plain = bytearray()
    for byte_enc in ed[3:]:
        byte = byte_enc ^ ((encrypted2 + unencrypted1) & 0xFF)
        plain.append(byte)
        encrypted2, encrypted1, unencrypted1 = encrypted1, byte_enc, byte

    ignored = bytes(plain[:ignored_length])
    (length,) = struct.unpack_from('<I', plain, ignored_length)
    data = bytes(plain[ignored_length + 4:])
    if len(data) != length:
        raise ValueError(f'DataLength 声明 {length}, 实际 {len(data)}')
    return data, proj_key, seed, ignored


def encrypt(data, proj_key, seed, ignored=b''):
    """MS-OVBA 2.4.3.2 Encryption，decrypt 的逆运算。"""
    if len(ignored) != (seed & 6) >> 1:
        raise ValueError('ignored 长度必须等于 (seed & 6) >> 1')
    version_enc = seed ^ 2
    proj_key_enc = seed ^ proj_key
    plain = ignored + struct.pack('<I', len(data)) + data

    unencrypted1, encrypted1, encrypted2 = proj_key, proj_key_enc, version_enc
    ed = bytearray([seed, version_enc, proj_key_enc])
    for byte in plain:
        byte_enc = byte ^ ((encrypted2 + unencrypted1) & 0xFF)
        ed.append(byte_enc)
        encrypted2, encrypted1, unencrypted1 = encrypted1, byte_enc, byte
    return ed.hex().upper()


def read_project(path):
    with olefile.OleFileIO(path) as ole:
        if not ole.exists(PROJECT_PATH):
            raise SystemExit(f'{path} 里没有 {PROJECT_PATH}，该文件不含 VBA 工程')
        return ole.openstream(PROJECT_PATH).read()


def parse_fields(raw):
    """取出 CMG/DPB/GC 三行的 hex 值。"""
    out = {}
    for line in raw.decode('gbk', errors='replace').splitlines():
        for key in ('CMG', 'DPB', 'GC'):
            prefix = key + '="'
            if line.startswith(prefix) and line.endswith('"'):
                out[key] = line[len(prefix):-1]
    return out


def inspect(path):
    fields = parse_fields(read_project(path))
    print(f'{path}\n{PROJECT_PATH} 共 {len(read_project(path))} 字节\n')
    for key in ('CMG', 'DPB', 'GC'):
        if key not in fields:
            print(f'{key}: 缺失（该项未设置）')
            continue
        hex_str = fields[key]
        data, proj_key, seed, ignored = decrypt(hex_str)
        # 用原始 seed / ignored 重新加密，能复现原 hex 才说明算法实现正确
        ok = encrypt(data, proj_key, seed, ignored) == hex_str.upper()
        print(f'{key}: seed=0x{seed:02X} projKey=0x{proj_key:02X} '
              f'ignored={ignored.hex().upper() or "-"} 回环校验={"通过" if ok else "失败"}')
        print(f'     data = {data.hex().upper()}  ({len(data)} 字节)')
        if key == 'CMG':
            (state,) = struct.unpack('<I', data)
            flags = [n for b, n in ((1, '用户锁定'), (2, '宿主锁定'), (4, 'VBE锁定')) if state & b]
            print(f'     ProjectProtectionState = 0x{state:08X} {flags or ["未保护"]}')
        elif key == 'GC':
            print(f'     ProjectVisibilityState = 0x{data[0]:02X} '
                  f'({"可见" if data[0] else "不可见"})')
        elif key == 'DPB':
            print(f'     {"无口令" if data == bytes(1) else "已设口令（此处为口令散列/明文块）"}')
        print()


def unlock(src, dst):
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit('拒绝原地修改：dst 必须是另一个路径')
    raw = read_project(src)
    fields = parse_fields(raw)
    if not fields:
        raise SystemExit('PROJECT 流里没有 CMG/DPB/GC，工程本来就没锁')

    # 沿用原有的 seed / projKey / ignored，只换 data，改动面最小
    new_values = {}
    for key, data in (('CMG', struct.pack('<I', 0)), ('DPB', b'\x00'), ('GC', b'\xff')):
        if key not in fields:
            continue
        _, proj_key, seed, ignored = decrypt(fields[key])
        new_values[key] = encrypt(data, proj_key, seed, ignored)

    text = raw.decode('gbk')
    for key, value in new_values.items():
        old_line = f'{key}="{fields[key]}"'
        new_line = f'{key}="{value}"'
        if old_line not in text:
            raise SystemExit(f'找不到 {old_line}')
        text = text.replace(old_line, new_line, 1)

    new_raw = text.encode('gbk')
    # olefile 只能等长覆写流，用行尾 CRLF 补齐到原长度
    if len(new_raw) > len(raw):
        raise SystemExit(f'新 PROJECT 流变长了（{len(new_raw)} > {len(raw)}），无法等长写回')
    pad = len(raw) - len(new_raw)
    new_raw += b'\r\n' * (pad // 2) + b'\r' * (pad % 2)
    assert len(new_raw) == len(raw)

    shutil.copy2(src, dst)
    with olefile.OleFileIO(dst, write_mode=True) as ole:
        ole.write_stream(PROJECT_PATH, new_raw)

    print(f'已写出 {dst}')
    for key in ('CMG', 'DPB', 'GC'):
        if key in new_values:
            print(f'  {key}: {fields[key]}\n     -> {new_values[key]}')
    print(f'  尾部补 {pad} 字节 CRLF 以保持流长度 {len(raw)}')


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'inspect':
        inspect(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'unlock':
        unlock(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
