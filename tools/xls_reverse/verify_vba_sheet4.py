# -*- coding: utf-8 -*-
"""
Verify the new Sheet4 VBA by opening with AutomationSecurity=1 (allow macros)
and calling RefreshDailyRows, then checking row count before/after.
"""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'outputs' / 'temp' / '\u98de\u8bfa\u65af\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868\uff08FNS\uff09_\u52a8\u6001\u7248.xls')

print('Target:', DST)
print('Size:', os.path.getsize(DST))

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
# AutomationSecurity=1 = msoAutomationSecurityLow — allow macros
try:
    xl.AutomationSecurity = 1
    print('AutomationSecurity set to 1 (allow macros)')
except Exception as e:
    print('AutomationSecurity warn:', e)

try:
    wb = xl.Workbooks.Open(DST, ReadOnly=False, IgnoreReadOnlyRecommended=True)
    xl.Calculation = -4135  # xlManual
    xl.EnableEvents = False
    xl.ScreenUpdating = False

    ws_daily = wb.Worksheets('\u91c7\u8d2d\u5165\u5e93\u65e5\u62a5\u8868')
    print(f'Sheet: {ws_daily.Name!r}  CodeName: {ws_daily.CodeName!r}')

    # Read current VBA to verify it was written
    vbcomp = wb.VBProject.VBComponents(ws_daily.CodeName)
    n_lines = vbcomp.CodeModule.CountOfLines
    print(f'VBA lines in module: {n_lines}')
    first_lines = vbcomp.CodeModule.Lines(1, min(n_lines, 20))
    print('--- First 20 VBA lines ---')
    for ln in first_lines.splitlines():
        print(' ', ln)
    print('--- End ---')

    # Check C2/F2/I2 values
    yr = ws_daily.Range("C2").Value
    mo = ws_daily.Range("F2").Value
    dy = ws_daily.Range("I2").Value
    print(f'Date cells: C2={yr!r}, F2={mo!r}, I2={dy!r}')

    # Scan for summary row and count detail rows (before)
    def count_detail_rows(ws, first_row=6):
        for r in range(first_row, first_row + 300):
            cf = ws.Cells(r, 1).Formula
            if 'TEXT(DATE' in cf and 'yy/m/d' in cf:
                return r - first_row, r
        return None, None

    detail_before, summary_row_before = count_detail_rows(ws_daily)
    b6_before = ws_daily.Cells(6, 2).Value
    print(f'BEFORE: detail_rows={detail_before}, summary_row={summary_row_before}, B6={b6_before!r}')

    # Enable events and call RefreshDailyRows
    xl.EnableEvents = True
    print('Calling Application.Run("RefreshDailyRows") ...')
    try:
        xl.Run("RefreshDailyRows")
        print('RefreshDailyRows OK')
    except Exception as e:
        print(f'Run error: {e}')
        # Try qualified name
        try:
            xl.Run("'" + os.path.basename(DST) + "'!RefreshDailyRows")
            print('RefreshDailyRows OK (qualified)')
        except Exception as e2:
            print(f'Qualified run error: {e2}')

    detail_after, summary_row_after = count_detail_rows(ws_daily)
    b6_after = ws_daily.Cells(6, 2).Value
    print(f'AFTER Run: detail_rows={detail_after}, summary_row={summary_row_after}, B6={b6_after!r}')

    # Test Worksheet_Change by setting I2 to different day
    test_day = (int(dy or 1) % 28) + 1
    print(f'Testing Worksheet_Change: I2 {dy} -> {test_day}')
    ws_daily.Range("I2").Value = test_day

    detail_change, summary_row_change = count_detail_rows(ws_daily)
    b6_change = ws_daily.Cells(6, 2).Value
    print(f'AFTER I2={test_day}: detail_rows={detail_change}, summary_row={summary_row_change}, B6={b6_change!r}')

    # Restore I2
    ws_daily.Range("I2").Value = dy
    xl.EnableEvents = False

    xl.Calculation = -4106  # xlAutomatic
    xl.Calculate()
    xl.ScreenUpdating = True

    wb.SaveAs(DST, FileFormat=56)
    print(f'Saved. Size: {os.path.getsize(DST)}')
    wb.Close(SaveChanges=False)

finally:
    xl.EnableEvents = True
    xl.Quit()

print('Done.')
