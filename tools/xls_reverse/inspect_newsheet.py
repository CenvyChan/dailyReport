# -*- coding: utf-8 -*-
"""详细查看 销售与入库占比 sheet 全部内容。"""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'data' / 'source' / '采购入库模板.xls')
DUMPS = ROOT / 'tools' / 'xls_reverse' / 'dumps'

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
xl.EnableEvents = False
try: xl.AutomationSecurity = 3
except: pass

try:
    wb = xl.Workbooks.Open(DST, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    ws = wb.Worksheets('销售与入库占比')
    ur = ws.UsedRange
    out=[]
    out.append(f'sheet: {ws.Name}  code={ws.CodeName}  used={ur.Address}  {ur.Rows.Count}r x {ur.Columns.Count}c')
    r0=ur.Row; c0=ur.Column
    for r in range(r0, r0+ur.Rows.Count):
        row=[]
        for c in range(c0, c0+ur.Columns.Count):
            cell=ws.Cells(r,c)
            try: f=cell.Formula
            except: f=None
            try: v=cell.Value
            except: v=None
            if (f is None or f=='') and (v is None or v==''):
                row.append('')
                continue
            if isinstance(f,str) and f.startswith('='):
                row.append(f'F:{f}')
            else:
                row.append(f'V:{v!r}')
        if any(x for x in row):
            out.append(f'  R{r}: ' + ' | '.join(row))
    nshp=int(ws.Shapes.Count)
    out.append(f'shapes: {nshp}')
    for i in range(1,nshp+1):
        sh=ws.Shapes.Item(i)
        out.append(f'  [{i}] {sh.Name} type={sh.Type}')
    print('\n'.join(out))
    (DUMPS / 'newsheet_dump.txt').write_text('\n'.join(out), encoding='utf-8')
    wb.Close(SaveChanges=False)
finally:
    xl.EnableEvents=True
    xl.Quit()
