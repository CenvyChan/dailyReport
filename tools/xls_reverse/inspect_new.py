# -*- coding: utf-8 -*-
"""检查 采购入库模板.xls 现状：所有 sheet 名、新增 sheet 的布局、B2 上下文。"""
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
try:
    xl.AutomationSecurity = 3
except Exception:
    pass

out = []
try:
    wb = xl.Workbooks.Open(DST, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    out.append('=== 所有工作表 ===')
    for i, ws in enumerate(wb.Worksheets):
        out.append(f'  [{i}] name={ws.Name!r}  code={ws.CodeName}  vis={ws.Visible}  used={ws.UsedRange.Address if ws.UsedRange else None}')
    out.append('')

    last = wb.Worksheets(wb.Worksheets.Count)
    out.append(f'=== 最后一张表: {last.Name!r} ===')
    ur = last.UsedRange
    if ur is None:
        out.append('  (空)')
    else:
        nrows = ur.Rows.Count
        ncols = ur.Columns.Count
        r0 = ur.Row
        c0 = ur.Column
        out.append(f'  used range: {ur.Address}  ({nrows}r x {ncols}c)  start R{r0}C{c0}')
        out.append('  内容（含公式）：')
        for r in range(r0, r0 + min(nrows, 60)):
            for c in range(c0, c0 + min(ncols, 30)):
                cell = last.Cells(r, c)
                try:
                    f = cell.Formula
                except Exception:
                    f = None
                try:
                    v = cell.Value
                except Exception:
                    v = None
                if f is None and (v is None or v == ''):
                    continue
                tag = ''
                if isinstance(f, str) and f.startswith('='):
                    tag = '[F]'
                else:
                    if v is None or v == '':
                        continue
                    tag = '[V]'
                try:
                    addr = cell.Address
                except Exception:
                    addr = f'R{r}C{c}'
                out.append(f'    {tag} {addr}: f={f!r} v={v!r}')

        try:
            nshp = int(last.Shapes.Count)
        except Exception:
            nshp = 0
        out.append(f'  shapes count: {nshp}')
        for i in range(1, nshp+1):
            sh = last.Shapes.Item(i)
            lc=mn=mx=''
            try:
                cf = sh.ControlFormat
                lc = cf.LinkedCell; mn = cf.Min; mx = cf.Max
            except Exception as e:
                lc = f'no cf: {e}'
            out.append(f'    [{i}] {sh.Name} type={sh.Type} linked={lc} min={mn} max={mx}')

    out.append('')
    out.append('=== 数据表表头 ===')
    ws_d = wb.Worksheets('数据表')
    for c in range(1, 8):
        out.append(f'  col{c}: {ws_d.Cells(1, c).Value!r}')

    out.append('')
    out.append('=== 汇率表样例 ===')
    ws_r = wb.Worksheets('汇率')
    for r in range(1, 6):
        out.append(f'  R{r}: A={ws_r.Cells(r,1).Value!r} B={ws_r.Cells(r,2).Value!r}')

    wb.Close(SaveChanges=False)
finally:
    xl.EnableEvents = True
    xl.Quit()

(DUMPS / 'inspect_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
