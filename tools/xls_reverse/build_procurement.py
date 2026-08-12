# -*- coding: utf-8 -*-
"""
基于 demo.xls 生成采购版模板 采购入库模板.xls
- 复用所有公式 / Spinner / VBA 工程
- 仅做表头与币别字符串替换（cell.Value 与 cell.Formula）
"""
import os, sys, shutil, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
SRC = str(ROOT / 'data' / 'source' / 'demo.xls')
DST = str(ROOT / 'data' / 'source' / '采购入库模板.xls')

shutil.copyfile(SRC, DST)
print('Copy ->', DST, os.path.getsize(DST), 'bytes')

REPLACEMENTS = [
    ('飞诺斯年度销售汇总表', '飞诺斯年度采购汇总表'),
    ('客户名称', '供应商名称'),
    ('业务跟单', '采购跟单'),
    ('销售类型', '币别'),
    ('销售金额', '采购金额'),
    ('销售年份', '采购年份'),
    ('出货日期', '入库日期'),
    ('出货数量', '入库数量'),
    ('客户', '供应商'),
    ('方式', '币别'),
    ('内销', '人民币'),
    ('外销', '美金'),
]

def repl(s):
    if not isinstance(s, str):
        return s
    for old, new in REPLACEMENTS:
        s = s.replace(old, new)
    return s

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
xl.EnableEvents = False
try:
    xl.AutomationSecurity = 3
except Exception:
    pass

try:
    wb = xl.Workbooks.Open(DST, ReadOnly=False, IgnoreReadOnlyRecommended=True)
    old_calc = xl.Calculation
    xl.Calculation = -4135
    xl.ScreenUpdating = False

    stats = {'val_changed': 0, 'frm_changed': 0, 'cells': 0}
    for ws in wb.Worksheets:
        ur = ws.UsedRange
        if ur is None:
            continue
        nrows = ur.Rows.Count
        ncols = ur.Columns.Count
        r0 = ur.Row
        c0 = ur.Column
        for r in range(r0, r0 + nrows):
            for c in range(c0, c0 + ncols):
                cell = ws.Cells(r, c)
                stats['cells'] += 1
                try:
                    f = cell.Formula
                except Exception:
                    f = None
                if isinstance(f, str) and f.startswith('='):
                    nf = repl(f)
                    if nf != f:
                        try:
                            cell.Formula = nf
                            stats['frm_changed'] += 1
                        except Exception as e:
                            print(f'  ! formula set fail {ws.Name}!{cell.Address}: {e}')
                    continue
                try:
                    v = cell.Value
                except Exception:
                    v = None
                if isinstance(v, str):
                    nv = repl(v)
                    if nv != v:
                        try:
                            cell.Value = nv
                            stats['val_changed'] += 1
                        except Exception as e:
                            print(f'  ! value set fail {ws.Name}!{cell.Address}: {e}')

    xl.Calculation = old_calc
    try:
        xl.Calculate()
    except Exception:
        pass
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    print('Saved (xls). stats:', stats)
    wb.Close(SaveChanges=False)
finally:
    xl.EnableEvents = True
    xl.Quit()

print('Done. size =', os.path.getsize(DST))
