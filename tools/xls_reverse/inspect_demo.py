# -*- coding: utf-8 -*-
"""勘查 demo.xls：sheet 列表 + 指定表的单元格值/公式/合并区/控件。"""
import sys

import win32com.client as win32

PATH = r'E:\DEV\dailyReport\outputs\temp\demo.xls'


def a1(row, col):
    s = ''
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return f'{s}{row}'


def dump_sheet(ws, max_row=60, max_col=20):
    used = ws.UsedRange
    print(f'--- [{ws.Name}] visible={ws.Visible} used={used.Row},{used.Column} '
          f'rows={used.Rows.Count} cols={used.Columns.Count}')
    lr = min(used.Row + used.Rows.Count - 1, max_row)
    lc = min(used.Column + used.Columns.Count - 1, max_col)
    for r in range(1, lr + 1):
        cells = []
        for c in range(1, lc + 1):
            cell = ws.Cells(r, c)
            f = cell.Formula
            v = cell.Text
            if f == '' and v == '':
                continue
            if isinstance(f, str) and f.startswith('='):
                cells.append(f'{a1(r, c)}={f}|{v}')
            else:
                cells.append(f'{a1(r, c)}:{v}')
        if cells:
            print(f'  R{r}: ' + '  '.join(cells))
    print(f'  合并区:')
    seen = set()
    for r in range(1, lr + 1):
        for c in range(1, lc + 1):
            ma = ws.Cells(r, c).MergeArea
            if ma.Count > 1:
                key = (ma.Row, ma.Column, ma.Rows.Count, ma.Columns.Count)
                if key not in seen:
                    seen.add(key)
                    print(f'    {a1(key[0], key[1])}:{a1(key[0]+key[2]-1, key[1]+key[3]-1)}')
    print(f'  Shapes:')
    for sh in ws.Shapes:
        try:
            tf = sh.TextFrame.Characters().Text
        except Exception:
            tf = ''
        print(f'    {sh.Name} type={sh.Type} text={tf!r} '
              f'at R{sh.TopLeftCell.Row}C{sh.TopLeftCell.Column}')
        try:
            print(f'      LinkedCell={sh.ControlFormat.LinkedCell}')
        except Exception:
            pass
        try:
            print(f'      OLE={sh.OLEFormat.Object.Name} '
                  f'Link={sh.OLEFormat.Object.LinkedCell}')
        except Exception:
            pass
    print()


def main():
    xl = win32.gencache.EnsureDispatch('Excel.Application')
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.EnableEvents = False
    xl.AutomationSecurity = 3
    wb = xl.Workbooks.Open(PATH, ReadOnly=True)
    try:
        print('SHEETS:')
        for ws in wb.Worksheets:
            print(f'  {ws.Index}: {ws.Name!r} CodeName={ws.CodeName} Visible={ws.Visible}')
        print()
        print('NAMES:')
        for nm in wb.Names:
            try:
                print(f'  {nm.Name} -> {nm.RefersTo}')
            except Exception as e:
                print(f'  {nm.Name} -> <err {e}>')
        print()
        targets = sys.argv[1:] or ['采购入库日报表', '数据表']
        for t in targets:
            try:
                dump_sheet(wb.Worksheets(t))
            except Exception as e:
                print(f'!! {t}: {e}')
    finally:
        wb.Close(False)
        xl.Quit()


if __name__ == '__main__':
    main()
