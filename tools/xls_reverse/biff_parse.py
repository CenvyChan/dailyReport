# -*- coding: utf-8 -*-
"""Parse BIFF8 (xls) records to extract sheet names and formula strings."""
import sys, struct, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import olefile

ROOT = pathlib.Path(__file__).parent.parent.parent
SRC = str(ROOT / 'data' / 'source' / 'demo.xls')

ole = olefile.OleFileIO(SRC)
wb = ole.openstream('Workbook').read()

def decode_name(data):
    flag = data[0]
    raw = data[1:]
    pass

# Walk records
recs = []
i = 0
while i + 4 <= len(wb):
    rt = struct.unpack('<H', wb[i:i+2])[0]
    ln = struct.unpack('<H', wb[i+2:i+4])[0]
    data = wb[i+4:i+4+ln]
    recs.append((i, rt, ln, data))
    i += 4 + ln
    if rt == 10 and len(recs) > 5:
        pass

def sheet_name_from_boundsheet(data):
    pos = struct.unpack('<I', data[0:4])[0]
    vis = data[4]
    cch = data[5]
    grbit = data[6]
    chars_raw = data[7:7 + (cch*2 if grbit & 1 else cch)]
    if grbit & 1:
        name = chars_raw.decode('utf-16-le', 'replace')
    else:
        name = chars_raw.decode('gbk', 'replace')
    return pos, vis, name

print('=== BOUNDSHEETS ===')
sheet_info = []
for off, rt, ln, data in recs:
    if rt == 0x0085:
        pos, vis, name = sheet_name_from_boundsheet(data)
        sheet_info.append((pos, vis, name))
        print(f'  pos={pos} vis={vis} name={name!r}')

sheet_starts = {pos: name for pos, vis, name in sheet_info}
sorted_starts = sorted(sheet_starts.items())
print()
print('Sheets in stream order:', [n for _, n in sorted_starts])

def sheet_for_offset(off):
    cur = None
    for pos, name in sorted_starts:
        if pos <= off:
            cur = name
        else:
            break
    return cur

def parse_formula_record(data, rec_offset):
    row = struct.unpack('<H', data[0:2])[0]
    col = struct.unpack('<H', data[2:4])[0]
    ixfe = struct.unpack('<H', data[4:6])[0]
    val_bytes = data[6:14]
    is_string_formula = (val_bytes[0] == 0xFF and val_bytes[1] in (0,1) and val_bytes[2:6] == b'\xFF\xFF\xFF\xFF')
    if not is_string_formula:
        try:
            fval = struct.unpack('<d', val_bytes)[0]
        except:
            fval = None
        return row, col, ('num', fval)
    else:
        return row, col, ('str', None)

def parse_ptg_tokens(rgce):
    tokens = []
    k = 0
    while k < len(rgce):
        ptg = rgce[k]
        t = ptg
        if t in (0x03, 0x40):
            val = struct.unpack('<h', rgce[k+1:k+3])[0]
            tokens.append(f'{val}')
            k += 3
        elif t in (0x04, 0x41):
            val = struct.unpack('<d', rgce[k+1:k+9])[0]
            tokens.append(f'{val}')
            k += 9
        elif t == 0x19:
            attr = rgce[k+1]
            sub = attr & 0xF0
            if sub == 0x20:
                k += 4
            else:
                k += 4
        elif t in (0x08, 0x48, 0x58, 0x68):
            tokens.append('BOOL')
            k += 2
        elif t in (0x41,):
            val = struct.unpack('<d', rgce[k+1:k+9])[0]
            tokens.append(f'{val}')
            k += 9
        elif t == 0x22 or t == 0x62 or t == 0x42:
            k += 1
        elif t == 0x44:
            idx = struct.unpack('<H', rgce[k+1:k+3])[0]
            tokens.append(f'NAME{idx}')
            k += 3
        elif t in (0x05, 0x45):
            grb = rgce[k+1]
            cch = rgce[k+2]
            if grb & 1:
                s = rgce[k+3:k+3+cch*2].decode('utf-16-le','replace')
                k += 3 + cch*2
            else:
                s = rgce[k+3:k+3+cch].decode('gbk','replace')
                k += 3 + cch
            tokens.append(repr(s))
        elif t in (0x24, 0x25, 0x26, 0x44, 0x46, 0x47, 0x54, 0x55, 0x56, 0x64, 0x65, 0x66):
            pass
        elif t in (0x25, 0x65):
            row = struct.unpack('<H', rgce[k+1:k+3])[0] & 0x3FFF
            col = struct.unpack('<H', rgce[k+3:k+5])[0] & 0x3FFF
            tokens.append(f'R{row}C{col}')
            k += 5
        else:
            k += 1
    return tokens

print()
print('=== FORMULA / STRING / LABEL records ===')
sst_strings = []
for off, rt, ln, data in recs:
    if rt == 0x00FC:
        cstUnique = struct.unpack('<I', data[4:8])[0]
        p = 8
        idx = 0
        while p < len(data) and idx < cstUnique:
            if p+3 > len(data): break
            cch = struct.unpack('<H', data[p:p+2])[0]
            grbit = data[p+2]
            p += 3
            flags = grbit
            if flags & 0x01:
                s = data[p:p+cch*2].decode('utf-16-le','replace')
                p += cch*2
            else:
                s = data[p:p+cch].decode('gbk','replace')
                p += cch
            if flags & 0x08:
                pass
            sst_strings.append(s)
            idx += 1
        print(f'SST: {len(sst_strings)} strings')
        for j, s in enumerate(sst_strings[:30]):
            print(f'  [{j}] {s!r}')
        break

print()
print('=== MULRK / RK / NUMBER / LABELSST / FORMULA per sheet ===')
cur_sheet = None
sheet_data = {}
sheet_bof_pos = {pos: name for pos, vis, name in [(s[0], s[1], s[2]) for s in sheet_info]}
positions = sorted(sheet_bof_pos.keys())

def get_sheet(off):
    s = None
    for p in positions:
        if p <= off:
            s = sheet_bof_pos[p]
        else:
            break
    return s

str_pending = None
for idx, (off, rt, ln, data) in enumerate(recs):
    if rt == 0x0006:
        sh = get_sheet(off)
        if not sh: continue
        r = struct.unpack('<H', data[0:2])[0]
        c = struct.unpack('<H', data[2:4])[0]
        val_bytes = data[6:14]
        if len(data) >= 16:
            cce = struct.unpack('<H', data[14:16])[0]
            rgce = data[16:16+cce]
        else:
            cce = 0
            rgce = b''
        is_str_formula = (val_bytes[0] == 0xFF and val_bytes[2:6] == b'\xFF\xFF\xFF\xFF')
        if is_str_formula:
            str_pending = (sh, r, c, rgce, cce)
        else:
            fval = struct.unpack('<d', val_bytes)[0]
            sheet_data.setdefault(sh, []).append((r, c, ('num', fval, rgce, cce)))
    elif rt == 0x0207:
        if str_pending:
            sh, r, c, rgce, cce = str_pending
            cch = struct.unpack('<H', data[0:2])[0]
            grbit = data[2]
            p = 3
            if grbit & 1:
                s = data[p:p+cch*2].decode('utf-16-le','replace')
            else:
                s = data[p:p+cch].decode('gbk','replace')
            sheet_data.setdefault(sh, []).append((r, c, ('str', s, rgce, cce)))
            str_pending = None
    elif rt == 0x00FD:
        sh = get_sheet(off)
        if not sh: continue
        r = struct.unpack('<H', data[0:2])[0]
        c = struct.unpack('<H', data[2:4])[0]
        isst = struct.unpack('<I', data[6:10])[0]
        s = sst_strings[isst] if isst < len(sst_strings) else f'<isst{isst}>'
        sheet_data.setdefault(sh, []).append((r, c, ('label', s)))
    elif rt == 0x027E:
        sh = get_sheet(off)
        if not sh: continue
        r = struct.unpack('<H', data[0:2])[0]
        c = struct.unpack('<H', data[2:4])[0]
        v = struct.unpack('<d', data[6:14])[0]
        sheet_data.setdefault(sh, []).append((r, c, ('num', v)))
    elif rt == 0x00BD:
        sh = get_sheet(off)
        if not sh: continue
        r = struct.unpack('<H', data[0:2])[0]
        c0 = struct.unpack('<H', data[2:4])[0]
        p = 4
        c = c0
        while p + 6 <= len(data) - 2:
            ixfe = struct.unpack('<H', data[p:p+2])[0]
            rk = struct.unpack('<I', data[p+2:p+6])[0]
            if rk & 2:
                v = struct.unpack('<i', struct.pack('<I', rk & ~2 | 0))[0] / 100
            elif rk & 1:
                d = struct.unpack('<d', b'\x00\x00\x00\x00\x00\x00\x00\x00')
                v = struct.unpack('<d', struct.pack('<I', 0) + struct.pack('<I', rk & ~1))[0]
            else:
                v = struct.unpack('<d', struct.pack('<I', 0) + struct.pack('<I', rk))[0]
            sheet_data.setdefault(sh, []).append((r, c, ('num', v)))
            c += 1
            p += 6

DUMPS = ROOT / 'tools' / 'xls_reverse' / 'dumps'
out_lines = []
print()
for sh, cells in sheet_data.items():
    print(f'--- Sheet: {sh} ---')
    cells.sort()
    for (r, c, info) in cells:
        col_letter = chr(65+c) if c < 26 else 'AA'
        addr = f'{col_letter}{r+1}'
        if info[0] == 'num':
            out_lines.append(f'{sh} {addr}: {info[1]}')
            print(f'  {addr}: {info[1]}')
        elif info[0] == 'str':
            out_lines.append(f'{sh} {addr}: =formula -> {info[1]!r}  [rgce len={len(info[2])}]')
            print(f'  {addr}: =formula -> {info[1]!r}  [rgce len={len(info[2])}]')
        elif info[0] == 'label':
            out_lines.append(f'{sh} {addr}: {info[1]!r}')
            print(f'  {addr}: {info[1]!r}')
(DUMPS / 'sheets_dump.txt').write_text('\n'.join(out_lines), encoding='utf-8')
