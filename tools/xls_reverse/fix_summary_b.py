# -*- coding: utf-8 -*-
"""补全 采购入库汇总表 B7:B18 的“人民币 入库数量”公式。
原模板该列缺失，对照 H7(今年人民币数量) 公式补出去年人民币数量。
B 列 = 去年(去年) 人民币 入库数量。
"""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'data' / 'source' / '采购入库模板.xls')

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
    ws = wb.Worksheets('采购入库汇总表')
    tmpl = ('=SUMIFS(数据表!$E:$E,数据表!$D:$D,">="&DATE($B$2-1,ROW()-ROW($H$6),1),'
            '数据表!$D:$D,"<="&EOMONTH(DATE($B$2-1,ROW()-ROW($H$6),1),0),'
            '数据表!$C:$C,"人民币")')
    for r in range(7, 19):
        ws.Cells(r, 2).Formula = tmpl
    wb.SaveAs(DST, FileFormat=56)
    wb.Close(SaveChanges=False)
    print('Patched B7:B18 with 人民币 入库数量 formula.')
finally:
    xl.EnableEvents = True
    xl.Quit()
print('size =', os.path.getsize(DST))
