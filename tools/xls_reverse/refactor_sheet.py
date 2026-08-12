# -*- coding: utf-8 -*-
"""
重构 销售与入库占比 sheet:
1) B2 = 年(上下选择), D2 = 月(上下选择), 去掉日
2) 加两个表单 Spinner 微调按钮, 分别链接 B2(年 2024~2050) / D2(月 1~12)
3) A5:A35 日期按 年+月 自动展开(去掉日维度)
4) B5:B35 入库金额改为本位币(人民币):
     =当天人民币金额 + 当天美金金额 * 当月汇率(VLOOKUP 汇率表)
   D5:D35 占比 = B/C 不变
   A36 月度合计 = SUM 不变
保留: B2 原日期格式 -> 改成常规整数显示年; D2 显示月整数。
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
    xl.Calculation = -4135
    xl.ScreenUpdating = False
    ws = wb.Worksheets('销售与入库占比')

    ws.Range('A2').Value = '统计年月'
    try:
        old_dt = ws.Range('B2').Value
        yr = int(old_dt.year) if old_dt else 2026
        mo = int(old_dt.month) if old_dt else 8
    except Exception:
        yr, mo = 2026, 8
    ws.Range('B2').Value = yr
    ws.Range('B2').NumberFormat = '0'
    ws.Range('C2').Value = '年'
    ws.Range('D2').Value = mo
    ws.Range('D2').NumberFormat = '0'
    ws.Range('E2').Value = '月'

    try:
        nshp = int(ws.Shapes.Count)
    except Exception:
        nshp = 0
    for i in range(nshp, 0, -1):
        try:
            ws.Shapes.Item(i).Delete()
        except Exception:
            pass

    from win32com.client import constants as C
    try:
        SP = C.xlSpinner
    except Exception:
        SP = 9

    def add_spinner(linked_cell, mn, mx, target_cell):
        L = target_cell.Left + target_cell.Width - 12
        T = target_cell.Top + 1
        W = 10
        H = target_cell.Height - 2
        sh = ws.Shapes.AddFormControl(Type=SP, Left=L, Top=T, Width=W, Height=H)
        sh.Name = 'Spinner ' + linked_cell.replace('$','')
        try:
            cf = sh.ControlFormat
            cf.LinkedCell = linked_cell
            cf.Min = mn
            cf.Max = mx
            cf.SmallChange = 1
        except Exception as e:
            print('cf err', e)
        return sh

    add_spinner('$B$2', 2024, 2050, ws.Range('B2'))
    add_spinner('$D$2', 1, 12, ws.Range('D2'))

    for r in range(5, 36):
        ws.Cells(r, 1).Formula = (
            f'=IF(ROW()-4<=DAY(EOMONTH(DATE($B$2,$D$2,1),0)),'
            f'DATE($B$2,$D$2,ROW()-4),"")'
        )
        ws.Cells(r, 1).NumberFormat = 'yyyy-mm-dd'

    for r in range(5, 36):
        ws.Cells(r, 2).Formula = (
            f'=IF($A{r}="","",'
            f'SUMIFS(数据表!$F$2:$F$5000,数据表!$D$2:$D$5000,$A{r},数据表!$C$2:$C$5000,"人民币")'
            f'+SUMIFS(数据表!$F$2:$F$5000,数据表!$D$2:$D$5000,$A{r},数据表!$C$2:$C$5000,"美金")'
            f'*IFERROR(VLOOKUP(TEXT(DATE($B$2,$D$2,1),"yyyy年m月份"),汇率!$A:$B,2,0),1))'
        )
        ws.Cells(r, 2).NumberFormat = '#,##0.00'

    for r in range(5, 36):
        ws.Cells(r, 3).NumberFormat = '#,##0.00'

    for r in range(5, 36):
        ws.Cells(r, 4).Formula = f'=IF(OR($A{r}="",$C{r}=0),"",$B{r}/$C{r})'
        ws.Cells(r, 4).NumberFormat = '0.00%'

    ws.Range('A36').Value = '月度合计'
    ws.Range('B36').Formula = '=SUM(B5:B35)'
    ws.Range('C36').Formula = '=SUM(C5:C35)'
    ws.Range('D36').Formula = '=IF(C36=0,"",B36/C36)'
    ws.Range('B36').NumberFormat = '#,##0.00'
    ws.Range('C36').NumberFormat = '#,##0.00'
    ws.Range('D36').NumberFormat = '0.00%'

    ws.Columns('A').ColumnWidth = 14
    ws.Columns('B').ColumnWidth = 16
    ws.Columns('C').ColumnWidth = 16
    ws.Columns('D').ColumnWidth = 10
    ws.Columns('E').ColumnWidth = 18
    ws.Columns('B').ColumnWidth = max(ws.Columns('B').ColumnWidth, 8)

    xl.Calculation = -4106
    try: xl.Calculate()
    except: pass
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    wb.Close(SaveChanges=False)
    print('Done. size =', os.path.getsize(DST))
finally:
    xl.EnableEvents = True
    xl.Quit()
