# -*- coding: utf-8 -*-
"""
Final VBA fix for 采购入库日报表 (Sheet4):
1. Move RefreshDailyRows to 模块2 (standard module, callable via Application.Run)
2. Sheet4 keeps only Worksheet_Change + minimal Worksheet_SelectionChange
3. Verify by Application.Run then test Worksheet_Change via I2 change
4. Save as FileFormat=56 (.xls)
"""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'outputs' / 'temp' / '\u98de\u8bfa\u65af\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868\uff08FNS\uff09_\u52a8\u6001\u7248.xls')

print('Target:', DST)
print('Size:', os.path.getsize(DST))

# VBA for Sheet4 module: only event handlers, delegates to standard module
SHEET4_VBA = r'''Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Intersect(Target, Range("A2:A20000")) Is Nothing Then Exit Sub
End Sub

Private Sub Worksheet_Change(ByVal Target As Range)
    If Intersect(Target, Me.Range("C2,F2,I2")) Is Nothing Then Exit Sub
    Application.EnableEvents = False
    RefreshDailyRows
    Application.EnableEvents = True
End Sub
'''

# RefreshDailyRows in standard module (模块2) — callable via Application.Run
MODULE2_VBA = r'''Sub RefreshDailyRows()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(Chr(37319) & Chr(36141) & Chr(20837) & Chr(24211) & Chr(26085) & Chr(25253) & Chr(34920))
    Dim yr As Long, mo As Long, dy As Long
    yr = ws.Range("C2").Value
    mo = ws.Range("F2").Value
    dy = ws.Range("I2").Value
    If yr = 0 Or mo = 0 Or dy = 0 Then Exit Sub

    Dim dataWs As Worksheet
    Set dataWs = ThisWorkbook.Worksheets(Chr(25968) & Chr(25454) & Chr(34920))

    Dim n As Long
    n = Application.WorksheetFunction.CountIf(dataWs.Range("D:D"), DateSerial(yr, mo, dy))
    If n < 1 Then n = 0

    Dim firstRow As Long
    firstRow = 6

    Dim summaryRow As Long
    summaryRow = 0
    Dim r As Long
    For r = firstRow To firstRow + 300
        Dim cellFormula As String
        cellFormula = ws.Cells(r, 1).Formula
        If InStr(cellFormula, "TEXT(DATE") > 0 And InStr(cellFormula, "yy/m/d") > 0 Then
            summaryRow = r
            Exit For
        End If
    Next r
    If summaryRow = 0 Then Exit Sub

    Application.ScreenUpdating = False

    Dim currentCount As Long
    currentCount = summaryRow - firstRow
    If currentCount > 0 Then
        ws.Rows(CStr(firstRow) & ":" & CStr(summaryRow - 1)).Delete Shift:=xlUp
    End If

    Dim rowsToInsert As Long
    rowsToInsert = IIf(n > 0, n, 1)
    ws.Rows(CStr(firstRow) & ":" & CStr(firstRow + rowsToInsert - 1)).Insert Shift:=xlDown

    Dim i As Long
    For i = 0 To rowsToInsert - 1
        Dim rn As Long
        rn = firstRow + i
        ws.Rows(rn).RowHeight = 16
        ws.Range(ws.Cells(rn, 2), ws.Cells(rn, 5)).Merge
        ws.Range(ws.Cells(rn, 6), ws.Cells(rn, 9)).Merge
        ws.Range(ws.Cells(rn, 10), ws.Cells(rn, 11)).Merge
        ws.Range(ws.Cells(rn, 12), ws.Cells(rn, 13)).Merge
        ws.Rows(rn).VerticalAlignment = xlCenter
        ws.Cells(rn, 2).HorizontalAlignment = xlLeft
        ws.Cells(rn, 1).HorizontalAlignment = xlCenter
    Next i

    Dim baseRef As String
    baseRef = "$A$" & CStr(firstRow)
    Dim shName As String
    shName = Chr(25968) & Chr(25454) & Chr(34920)
    Dim rmb As String
    rmb = Chr(20154) & Chr(27665) & Chr(24065)
    Dim usd As String
    usd = Chr(32654) & Chr(37329)

    For i = 1 To n
        Dim rowNum As Long
        rowNum = firstRow + i - 1
        ws.Cells(rowNum, 1).Value = i
        ws.Cells(rowNum, 2).Formula = "=IF(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",INDEX(" & shName & "!$A:$A,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),"""")"
        ws.Cells(rowNum, 6).Formula = "=IF(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",INDEX(" & shName & "!$E:$E,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),"""")"
        ws.Cells(rowNum, 10).Formula = "=IF(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",INDEX(" & shName & "!$C:$C,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),"""")"
        ws.Cells(rowNum, 12).Formula = "=IF(AND(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",$J" & rowNum & "==""" & rmb & """),INDEX(" & shName & "!$F:$F,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),"""")"
        ws.Cells(rowNum, 14).Formula = "=IF(AND(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",$J" & rowNum & "==""" & usd & """),INDEX(" & shName & "!$F:$F,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),0)"
        ws.Cells(rowNum, 15).Formula = "=IF(COUNTIF(" & shName & "!D:D,DATE($C$2,$F$2,$I$2))>=$A" & rowNum & ",INDEX(" & shName & "!$B:$B,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2)," & shName & "!$D:$D,0)),0)+ROW()-ROW(" & baseRef & ")),"""")"
    Next i

    Dim s1 As Long, s2 As Long, s3 As Long
    s1 = firstRow + rowsToInsert
    s2 = s1 + 1
    s3 = s1 + 2
    Dim detailEnd As Long
    detailEnd = s1 - 1

    ws.Cells(s1, 1).Formula = "=TEXT(DATE(C2,F2,I2),""yy/m/d"")&""" & Chr(21512) & Chr(35745) & Chr(65306) & """"
    ws.Cells(s1, 6).Formula = "=SUM(F" & firstRow & ":F" & detailEnd & ")"
    ws.Cells(s1, 12).Formula = "=SUM(L" & firstRow & ":L" & detailEnd & ")"
    ws.Cells(s1, 14).Formula = "=SUM(N" & firstRow & ":N" & detailEnd & ")"

    ws.Cells(s2, 1).Formula = "=TEXT(DATE(C2,F2,1),""yy/m/d"")&""-""&TEXT(DATE(C2,F2,I2),""m/d"")&""" & Chr(32047) & Chr(35745) & Chr(65306) & """"
    ws.Cells(s2, 6).Formula = "=SUMIFS(" & shName & "!$E:$E," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&DATE(C2,F2,I2))"
    ws.Cells(s2, 12).Formula = "=SUMIFS(" & shName & "!$F:$F," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&DATE(C2,F2,I2)," & shName & "!$C:$C,""" & rmb & """)"
    ws.Cells(s2, 14).Formula = "=SUMIFS(" & shName & "!$F:$F," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&DATE(C2,F2,I2)," & shName & "!$C:$C,""" & usd & """)"

    ws.Cells(s3, 1).Formula = "=TEXT(DATE(C2,F2,I2),""yy/m"")&""" & Chr(26376) & Chr(24635) & Chr(35745) & Chr(65306) & """"
    ws.Cells(s3, 6).Formula = "=SUMIFS(" & shName & "!$E:$E," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&EOMONTH(DATE(C2,F2,1),0))"
    ws.Cells(s3, 12).Formula = "=SUMIFS(" & shName & "!$F:$F," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&EOMONTH(DATE(C2,F2,1),0)," & shName & "!$C:$C,""" & rmb & """)"
    ws.Cells(s3, 14).Formula = "=SUMIFS(" & shName & "!$F:$F," & shName & "!$D:$D,"">=""&DATE(C2,F2,1)," & shName & "!$D:$D,""<=""&EOMONTH(DATE(C2,F2,1),0)," & shName & "!$C:$C,""" & usd & """)"

    Application.ScreenUpdating = True
End Sub
'''

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
xl.AutomationSecurity = 1

try:
    wb = xl.Workbooks.Open(DST, ReadOnly=False, IgnoreReadOnlyRecommended=True)
    xl.Calculation = -4135
    xl.EnableEvents = False
    xl.ScreenUpdating = False

    vbp = wb.VBProject

    # --- Rewrite Sheet4: only event handlers ---
    sh4_comp = vbp.VBComponents('Sheet4')
    sh4_cm = sh4_comp.CodeModule
    if sh4_cm.CountOfLines > 0:
        sh4_cm.DeleteLines(1, sh4_cm.CountOfLines)
    sh4_cm.InsertLines(1, SHEET4_VBA)
    print(f'Sheet4 rewritten: {sh4_cm.CountOfLines} lines')

    # --- Rewrite 模块2: put RefreshDailyRows here ---
    # Find the empty standard module by iterating (avoid encoding issues with Chinese names)
    mod2_comp = None
    for _i in range(1, vbp.VBComponents.Count + 1):
        _c = vbp.VBComponents.Item(_i)
        if _c.Type == 1 and _c.CodeModule.CountOfLines == 0:
            mod2_comp = _c
            print(f'Using empty standard module: {_c.Name!r}')
            break
    if mod2_comp is None:
        # Fall back: add a new standard module
        mod2_comp = vbp.VBComponents.Add(1)
        mod2_comp.Name = 'DailyRowsModule'
        print('Added new standard module: DailyRowsModule')
    # 模块2
    mod2_cm = mod2_comp.CodeModule
    if mod2_cm.CountOfLines > 0:
        mod2_cm.DeleteLines(1, mod2_cm.CountOfLines)
    mod2_cm.InsertLines(1, MODULE2_VBA)
    print(f'\u6a21\u51642 rewritten: {mod2_cm.CountOfLines} lines')

    # --- Verify row count before ---
    ws_daily = wb.Worksheets('\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868')
    yr = ws_daily.Range('C2').Value
    mo_val = ws_daily.Range('F2').Value
    dy = ws_daily.Range('I2').Value
    print(f'Date: C2={yr}, F2={mo_val}, I2={dy}')

    def count_detail(ws, first=6):
        for r in range(first, first + 300):
            cf = ws.Cells(r, 1).Formula
            if 'TEXT(DATE' in cf and 'yy/m/d' in cf:
                return r - first, r
        return None, None

    det_b, sum_b = count_detail(ws_daily)
    b6_b = ws_daily.Cells(6, 2).Value
    print(f'BEFORE: detail_rows={det_b}, summary_row={sum_b}, B6={b6_b!r}')

    # --- Run RefreshDailyRows from standard module ---
    xl.EnableEvents = True
    wb_name = os.path.basename(DST)
    calls = [
        'RefreshDailyRows',
        f"'{wb_name}'!RefreshDailyRows",
        '\u6a21\u51642.RefreshDailyRows',
        f"'{wb_name}'!\u6a21\u51642.RefreshDailyRows",
    ]
    ran = False
    for call in calls:
        try:
            xl.Run(call)
            print(f'OK: Application.Run("{call}")')
            ran = True
            break
        except Exception as e:
            print(f'  FAIL "{call}": {str(e)[:120]}')

    det_a, sum_a = count_detail(ws_daily)
    b6_a = ws_daily.Cells(6, 2).Value
    print(f'AFTER Run: detail_rows={det_a}, summary_row={sum_a}, B6={b6_a!r}')

    # --- Test Worksheet_Change ---
    dy_cur = ws_daily.Range('I2').Value
    test_day = (int(dy_cur or 1) % 28) + 1
    print(f'Testing Worksheet_Change: I2 {dy_cur} -> {test_day}')
    xl.EnableEvents = True
    ws_daily.Range('I2').Value = test_day

    det_c, sum_c = count_detail(ws_daily)
    b6_c = ws_daily.Cells(6, 2).Value
    print(f'AFTER I2={test_day}: detail_rows={det_c}, summary_row={sum_c}, B6={b6_c!r}')

    # Restore
    ws_daily.Range('I2').Value = dy_cur
    xl.EnableEvents = False

    xl.Calculation = -4106
    xl.Calculate()
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    print(f'Saved. Size: {os.path.getsize(DST)}')
    wb.Close(SaveChanges=False)

finally:
    xl.EnableEvents = True
    xl.Quit()

print('COM phase done.')
