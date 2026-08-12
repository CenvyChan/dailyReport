# -*- coding: utf-8 -*-
"""验证采购入库模板.xls: 表头/币别/公式/Spinner/VBA 是否齐全正确。"""
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
    out.append('=== 表头与文本值检查 ===')
    for ws in wb.Worksheets:
        ur = ws.UsedRange
        if ur is None: continue
        for r in range(ur.Row, ur.Row + ur.Rows.Count):
            for c in range(ur.Column, ur.Column + ur.Columns.Count):
                cell = ws.Cells(r, c)
                try: v = cell.Value
                except: v = None
                if isinstance(v, str) and v.strip():
                    if any(k in v for k in ['采购','币别','供应商','入库','人民币','美金','汇率','飞诺斯','跟单','负责人']):
                        out.append(f'  {ws.Name}!R{r}C{c}: {v!r}')
    out.append('')

    out.append('=== 关键公式抽查 ===')
    ws_day = wb.Worksheets('采购入库日报表')
    for addr in ['O2','B6','L6','N6','L17','N17','L18','N18','A16','A17','A18']:
        out.append(f'  日报表!{addr}: {ws_day.Range(addr).Formula}')
    ws_sum = wb.Worksheets('采购入库汇总表')
    for addr in ['B4','H4','B7','G7','K7','B19']:
        out.append(f'  汇总表!{addr}: {ws_sum.Range(addr).Formula}')
    out.append('')

    out.append('=== Spinner 微调按钮 ===')
    for ws in wb.Worksheets:
        n = int(ws.Shapes.Count)
        if n == 0: continue
        for i in range(1, n+1):
            sh = ws.Shapes.Item(i)
            lc=''; mn=''; mx=''
            try:
                cf = sh.ControlFormat
                lc = cf.LinkedCell; mn = cf.Min; mx = cf.Max
            except Exception as e:
                lc = f'err:{e}'
            out.append(f'  {ws.Name} [{i}] {sh.Name} linked={lc} min={mn} max={mx}')
    out.append('')

    out.append('=== VBA 工程 ===')
    try:
        vbp = wb.VBProject
        out.append(f'  VBProject.Name = {vbp.Name!r}')
        for vbc in vbp.VBComponents:
            out.append(f'  comp: {vbc.Name}  type={vbc.Type}')
    except Exception as e:
        out.append(f'  VBProject access err: {e}')
    out.append('')

    out.append('=== 数据表 ===')
    ws_d = wb.Worksheets('数据表')
    ur = ws_d.UsedRange
    for r in range(ur.Row, ur.Row + ur.Rows.Count):
        row = []
        for c in range(ur.Column, ur.Column + ur.Columns.Count):
            v = ws_d.Cells(r, c).Value
            row.append(repr(v) if v is not None else '')
        out.append(f'  R{r}: ' + ' | '.join(row))
    out.append('')

    out.append('=== 基础信息表 ===')
    ws_b = wb.Worksheets('基础信息表')
    ur = ws_b.UsedRange
    for r in range(ur.Row, ur.Row + ur.Rows.Count):
        row = []
        for c in range(ur.Column, ur.Column + ur.Columns.Count):
            v = ws_b.Cells(r, c).Value
            row.append(repr(v) if v is not None else '')
        out.append(f'  R{r}: ' + ' | '.join(row))

    wb.Close(SaveChanges=False)
finally:
    xl.EnableEvents = True
    xl.Quit()

(DUMPS / 'verify_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
