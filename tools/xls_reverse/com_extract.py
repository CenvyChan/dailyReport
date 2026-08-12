# -*- coding: utf-8 -*-
"""Read formulas from demo.xls via Excel COM (read-only)."""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
SRC = str(ROOT / 'data' / 'source' / 'demo.xls')
DUMPS = ROOT / 'tools' / 'xls_reverse' / 'dumps'

print('Opening (read-only):', SRC)

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
try:
    wb = xl.Workbooks.Open(SRC, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    out = []
    for ws in wb.Worksheets:
        out.append(f'=== Sheet: {ws.Name}  (code name: {ws.CodeName})  {ws.UsedRange.Rows.Count}r x {ws.UsedRange.Columns.Count}c ===')
        ur = ws.UsedRange
        nrows = ur.Rows.Count
        ncols = ur.Columns.Count
        r0 = ur.Row
        c0 = ur.Column
        for r in range(r0, r0 + min(nrows, 200)):
            for c in range(c0, c0 + min(ncols, 60)):
                cell = ws.Cells(r, c)
                f = cell.Formula
                v = cell.Value
                if f is None and (v is None or v == ''):
                    continue
                addr = cell.Address
                if isinstance(f, str) and f.startswith('='):
                    out.append(f'  {addr}: {f}')
                else:
                    if v is not None and v != '':
                        out.append(f'  {addr}: {v!r}')
        out.append('')
    out.append('=== Defined Names ===')
    for nm in wb.Names:
        try:
            out.append(f'  {nm.Name} = {nm.RefersTo}  (visible={not nm.Visible})')
        except Exception as e:
            out.append(f'  <name err {e}>')
    print('\n'.join(out))
    wb.Close(SaveChanges=False)
finally:
    xl.Quit()

(DUMPS / 'formulas_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('WROTE formulas_dump.txt')
