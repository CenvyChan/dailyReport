# -*- coding: utf-8 -*-
"""
修复 销售与入库占比:
1. spinner 不再压在数值上 -> 放到独立单元格右侧, 数值列加宽可见
2. 强制工作簿为自动计算模式 (Application.Calculation = xlAutomatic + CalculateBeforeSave)
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
    ws = wb.Worksheets('销售与入库占比')

    try:
        nshp = int(ws.Shapes.Count)
    except Exception:
        nshp = 0
    for i in range(nshp, 0, -1):
        try:
            sh = ws.Shapes.Item(i)
            sh.Delete()
        except Exception:
            pass

    ws.Range('A2').Value = '统计年月：'
    if not ws.Range('B2').Value:
        ws.Range('B2').Value = 2026
    ws.Range('B2').NumberFormat = '0'
    ws.Range('C2').Value = '年'
    if not ws.Range('D2').Value:
        ws.Range('D2').Value = 8
    ws.Range('D2').NumberFormat = '0'
    ws.Range('E2').Value = '月'

    ws.Columns('A').ColumnWidth = 14
    ws.Columns('B').ColumnWidth = 8
    ws.Columns('C').ColumnWidth = 6
    ws.Columns('D').ColumnWidth = 6
    ws.Columns('E').ColumnWidth = 6
    ws.Rows('2').RowHeight = 22

    def add_spinner(linked_cell, mn, mx, host_cell):
        L = host_cell.Left + host_cell.Width - 9
        T = host_cell.Top + 2
        W = 8
        H = host_cell.Height - 4
        sh = ws.Shapes.AddFormControl(Type=9, Left=L, Top=T, Width=W, Height=H)
        sh.Name = 'Spn_' + linked_cell.replace('$', '')
        cf = sh.ControlFormat
        cf.LinkedCell = linked_cell
        cf.Min = mn
        cf.Max = mx
        cf.SmallChange = 1
        return sh

    add_spinner('$B$2', 2024, 2050, ws.Range('C2'))
    add_spinner('$D$2', 1, 12, ws.Range('E2'))

    for r in range(5, 36):
        ws.Cells(r, 1).Formula = (
            f'=IF(ROW()-4<=DAY(EOMONTH(DATE($B$2,$D$2,1),0)),'
            f'DATE($B$2,$D$2,ROW()-4),"")'
        )
        ws.Cells(r, 1).NumberFormat = 'yyyy-mm-dd'
        ws.Cells(r, 2).Formula = (
            f'=IF($A{r}="","",'
            f'SUMIFS(数据表!$F$2:$F$5000,数据表!$D$2:$D$5000,$A{r},数据表!$C$2:$C$5000,"人民币")'
            f'+SUMIFS(数据表!$F$2:$F$5000,数据表!$D$2:$D$5000,$A{r},数据表!$C$2:$C$5000,"美金")'
            f'*IFERROR(VLOOKUP(TEXT(DATE($B$2,$D$2,1),"yyyy年m月份"),汇率!$A:$B,2,0),1))'
        )
        ws.Cells(r, 2).NumberFormat = '#,##0.00'
        ws.Cells(r, 3).NumberFormat = '#,##0.00'
        ws.Cells(r, 4).Formula = f'=IF(OR($A{r}="",$C{r}=0),"",$B{r}/$C{r})'
        ws.Cells(r, 4).NumberFormat = '0.00%'

    xl.Calculation = -4106
    try:
        wb.Application.CalculateBeforeSave = True
    except Exception as e:
        print('CalculateBeforeSave err', e)
    xl.Calculate()

    wb.SaveAs(DST, FileFormat=56)
    wb.Close(SaveChanges=False)
    print('Saved. calc set to auto.')
finally:
    xl.EnableEvents = True
    xl.Quit()
print('size =', os.path.getsize(DST))
