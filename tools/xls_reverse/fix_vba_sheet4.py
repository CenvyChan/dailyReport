# -*- coding: utf-8 -*-
"""
Replace Sheet4 (采购入库日报表) VBA with a clean version that:
- Uses Worksheet_Change on C2/F2/I2 to fire RefreshDailyRows
- Avoids Chinese characters in VBA string comparisons (uses Chr() sequences)
- Detects summary row by formula pattern TEXT(DATE / yy/m/d (pure ASCII)
- Standalone RefreshDailyRows Sub callable via Application.Run
"""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'outputs' / 'temp' / '\u98de\u8bfa\u65af\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868\uff08FNS\uff09_\u52a8\u6001\u7248.xls')

print('Target:', DST)
print('Exists:', os.path.exists(DST))

NEW_VBA = r'''Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Intersect(Target, Range("A2:A20000")) Is Nothing Then Exit Sub
End Sub

Sub RefreshDailyRows()
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

Private Sub Worksheet_Change(ByVal Target As Range)
    If Intersect(Target, Me.Range("C2,F2,I2")) Is Nothing Then Exit Sub
    Application.EnableEvents = False
    RefreshDailyRows
    Application.EnableEvents = True
End Sub
'''

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
    xl.Calculation = -4135  # xlManual
    xl.ScreenUpdating = False

    # Find Sheet4 by codename or sheet name
    target_ws = None
    target_sheet_name = '\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868'
    for ws in wb.Worksheets:
        print(f'  Sheet: {ws.Name!r}  codename: {ws.CodeName!r}')
        if ws.Name == target_sheet_name or ws.CodeName == 'Sheet4':
            target_ws = ws
            break

    if target_ws is None:
        print('ERROR: Could not find sheet 采购入库日报表 / Sheet4')
        wb.Close(SaveChanges=False)
        raise SystemExit(1)

    print(f'Found target sheet: {target_ws.Name!r} ({target_ws.CodeName!r})')

    # Read existing VBA before replacing
    try:
        vbcomp = wb.VBProject.VBComponents(target_ws.CodeName)
        existing = vbcomp.CodeModule.Lines(1, vbcomp.CodeModule.CountOfLines)
        print('--- Existing VBA (first 30 lines) ---')
        for line in existing.splitlines()[:30]:
            print(' ', line)
        print('--- End existing VBA ---')
    except Exception as e:
        print(f'Could not read existing VBA: {e}')
        vbcomp = None

    # Clear and rewrite
    if vbcomp is not None:
        cm = vbcomp.CodeModule
        total_lines = cm.CountOfLines
        if total_lines > 0:
            cm.DeleteLines(1, total_lines)
        cm.InsertLines(1, NEW_VBA)
        print(f'VBA written: {cm.CountOfLines} lines')
    else:
        print('Attempting to access VBComponent by component name...')
        try:
            vbcomp2 = wb.VBProject.VBComponents(target_ws.CodeName)
            cm = vbcomp2.CodeModule
            if cm.CountOfLines > 0:
                cm.DeleteLines(1, cm.CountOfLines)
            cm.InsertLines(1, NEW_VBA)
            print(f'VBA written via fallback: {cm.CountOfLines} lines')
        except Exception as e2:
            print(f'VBA write failed: {e2}')
            raise

    # --- Row count BEFORE test ---
    # Re-enable events for the test, set I2 to trigger change
    xl.EnableEvents = True
    ws_daily = target_ws

    # Record pre-state
    i2_before = ws_daily.Range("I2").Value
    row_count_before = None
    # Count detail rows: scan from row 6 for summary row
    for r in range(6, 310):
        cf = ws_daily.Cells(r, 1).Formula
        if 'TEXT(DATE' in cf and 'yy/m/d' in cf:
            row_count_before = r - 6
            break
    print(f'I2 before: {i2_before!r}, detail rows before: {row_count_before!r}')

    # Run RefreshDailyRows directly to verify
    print('Running RefreshDailyRows via Application.Run ...')
    try:
        xl.Run("RefreshDailyRows")
        print('RefreshDailyRows ran without error')
    except Exception as e:
        print(f'Application.Run error: {e}')

    # Record post-state
    row_count_after = None
    for r in range(6, 310):
        cf = ws_daily.Cells(r, 1).Formula
        if 'TEXT(DATE' in cf and 'yy/m/d' in cf:
            row_count_after = r - 6
            break
    b6_val = ws_daily.Cells(6, 2).Value
    print(f'Detail rows after: {row_count_after!r}')
    print(f'B6 value (first supplier): {b6_val!r}')

    # Now test Worksheet_Change by changing I2 to a different day
    test_day = (int(i2_before) % 28) + 1  # change to different day (cycle 1-28)
    print(f'Testing Worksheet_Change: setting I2 from {i2_before} -> {test_day}')
    ws_daily.Range("I2").Value = test_day
    # Wait briefly (Events should have fired synchronously)
    row_count_change_test = None
    for r in range(6, 310):
        cf = ws_daily.Cells(r, 1).Formula
        if 'TEXT(DATE' in cf and 'yy/m/d' in cf:
            row_count_change_test = r - 6
            break
    b6_after_change = ws_daily.Cells(6, 2).Value
    print(f'After I2={test_day}: detail rows={row_count_change_test!r}, B6={b6_after_change!r}')
    # Restore I2
    ws_daily.Range("I2").Value = i2_before

    xl.EnableEvents = False
    xl.Calculation = -4106  # xlAutomatic
    xl.Calculate()
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    print(f'Saved. File size: {os.path.getsize(DST)}')
    wb.Close(SaveChanges=False)

finally:
    xl.EnableEvents = True
    xl.Quit()

print('Script complete.')
