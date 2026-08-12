# -*- coding: utf-8 -*-
"""
采购入库汇总表 G/L 列套用本位币金额公式:
  G列(去年 B2-1): 本位币 = 人民币金额(E) + 美金金额×当月汇率
  L列(今年 B2)  : 本位币 = 人民币金额(J) + 美金金额×当月汇率
月份由 ROW()-ROW($I$6) 映射为 1~12.
汇率匹配用 "yyyy年m月份" (汇率表 A 列月份不补零).
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
try: xl.AutomationSecurity = 3
except: pass

try:
    wb = xl.Workbooks.Open(DST, ReadOnly=False, IgnoreReadOnlyRecommended=True)
    xl.ScreenUpdating = False
    ws = wb.Worksheets('采购入库汇总表')

    for r in range(7, 19):
        ws.Cells(r, 7).Formula = (
            f'=E{r}'
            f'+SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&DATE($B$2-1,ROW()-ROW($I$6),1),'
            f'数据表!$D:$D,"<="&EOMONTH(DATE($B$2-1,ROW()-ROW($I$6),1),0),'
            f'数据表!$C:$C,"美金")'
            f'*IFERROR(VLOOKUP(TEXT(DATE($B$2-1,ROW()-ROW($I$6),1),"yyyy年m月份"),'
            f'汇率!$A:$B,2,0),1)'
        )
        ws.Cells(r, 7).NumberFormat = '#,##0.00'

        ws.Cells(r, 12).Formula = (
            f'=J{r}'
            f'+SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&DATE($B$2,ROW()-ROW($I$6),1),'
            f'数据表!$D:$D,"<="&EOMONTH(DATE($B$2,ROW()-ROW($I$6),1),0),'
            f'数据表!$C:$C,"美金")'
            f'*IFERROR(VLOOKUP(TEXT(DATE($B$2,ROW()-ROW($I$6),1),"yyyy年m月份"),'
            f'汇率!$A:$B,2,0),1)'
        )
        ws.Cells(r, 12).NumberFormat = '#,##0.00'

    ws.Cells(19, 7).Formula = '=SUM(G7:G18)'
    ws.Cells(19, 7).NumberFormat = '#,##0.00'
    ws.Cells(19, 12).Formula = '=SUM(L7:L18)'
    ws.Cells(19, 12).NumberFormat = '#,##0.00'

    ws.Columns('G').ColumnWidth = 14
    ws.Columns('L').ColumnWidth = 14

    xl.Calculation = -4106
    xl.Calculate()
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    wb.Close(SaveChanges=False)
    print('Done. G/L 本位币公式已写入.')
finally:
    xl.EnableEvents = True
    xl.Quit()
print('size =', os.path.getsize(DST))
