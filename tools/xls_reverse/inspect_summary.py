# -*- coding: utf-8 -*-
"""检查 采购入库汇总表 当前布局, 含 G/L 列新增内容。"""
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

out = []
try:
    wb = xl.Workbooks.Open(DST, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    xl.Calculation = -4106
    ws = wb.Worksheets('采购入库汇总表')
    ur = ws.UsedRange
    out.append(f'used range: {ur.Address}  {ur.Rows.Count}r x {ur.Columns.Count}c')
    out.append('')
    out.append('=== 表头区 R1-R6 (值 + 公式 + 格式) ===')
    for r in range(1, 7):
        for c in range(1, 13):
            cell = ws.Cells(r, c)
            try: v = cell.Value
            except: v = None
            try: f = cell.Formula
            except: f = None
            if (v is None or v == '') and (f is None or f == ''):
                continue
            col_letter = chr(64+c) if c<=26 else 'AA'
            if isinstance(f, str) and f.startswith('='):
                out.append(f'  {col_letter}{r}: [F] {f}')
            else:
                out.append(f'  {col_letter}{r}: [V] {v!r}')
        out.append('')
    out.append('=== 数据区 R7-R18 (各列公式/值) ===')
    for r in range(7, 19):
        out.append(f'-- R{r} (月份={ws.Cells(r,1).Value}) --')
        for c in range(1, 13):
            cell = ws.Cells(r, c)
            try: v = cell.Value
            except: v = None
            try: f = cell.Formula
            except: f = None
            if (v is None or v == '') and (f is None or f == ''):
                continue
            col_letter = chr(64+c)
            if isinstance(f, str) and f.startswith('='):
                out.append(f'  {col_letter}{r}: [F] {f}   = {v!r}')
            else:
                out.append(f'  {col_letter}{r}: [V] {v!r}')
    out.append('')
    out.append('=== 合计行 R19 ===')
    for c in range(1, 13):
        cell = ws.Cells(19, c)
        try: v = cell.Value
        except: v = None
        try: f = cell.Formula
        except: f = None
        if (v is None or v == '') and (f is None or f == ''):
            continue
        col_letter = chr(64+c)
        if isinstance(f, str) and f.startswith('='):
            out.append(f'  {col_letter}19: [F] {f}   = {v!r}')
        else:
            out.append(f'  {col_letter}19: [V] {v!r}')
    out.append('')
    out.append('=== 列宽 ===')
    for c in range(1, 13):
        out.append(f'  {chr(64+c)}: {ws.Columns(c).ColumnWidth}')
    wb.Close(SaveChanges=False)
finally:
    xl.EnableEvents = True
    xl.Quit()

(DUMPS / 'summary_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
