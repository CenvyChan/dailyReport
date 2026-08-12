# -*- coding: utf-8 -*-
"""Dump structure/formulas/controls of an .xls via Excel COM (macros force-disabled)."""
import os, sys, json
import win32com.client as win32


def a1(row, col):
    s = ''
    while col > 0:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return f'{s}{row}'


def addr_of(rng):
    """Relative A1 address (or range) computed without COM .Address."""
    r, c = rng.Row, rng.Column
    nr, nc = rng.Rows.Count, rng.Columns.Count
    if nr == 1 and nc == 1:
        return a1(r, c)
    return f'{a1(r, c)}:{a1(r + nr - 1, c + nc - 1)}'


SRC = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else 'demo.xls')
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else '.tmp/xls_dump.json')

xl = win32.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
xl.AutomationSecurity = 3          # force-disable macros
xl.EnableEvents = False

wb = xl.Workbooks.Open(SRC, ReadOnly=True, UpdateLinks=0)
doc = {'file': SRC, 'sheets': [], 'names': []}

try:
    for nm in wb.Names:
        try:
            doc['names'].append({'name': nm.Name, 'refersTo': nm.RefersTo})
        except Exception as e:
            doc['names'].append({'name': '?', 'err': str(e)})

    for ws in wb.Worksheets:
        s = {'name': ws.Name, 'index': ws.Index, 'visible': int(ws.Visible),
             'codeName': ws.CodeName, 'cells': [], 'shapes': [], 'merged': [],
             'validations': [], 'condformats': [], 'colwidths': {}, 'rowheights': {}}
        ur = ws.UsedRange
        r1, c1 = ur.Row, ur.Column
        nr, nc = ur.Rows.Count, ur.Columns.Count
        s['usedRange'] = addr_of(ur)
        s['dims'] = [r1, c1, nr, nc]
        try:
            vals, fmls = ur.Value, ur.Formula
            if nr == 1 and nc == 1:
                vals, fmls = ((vals,),), ((fmls,),)
            elif nr == 1:
                vals, fmls = (vals,), (fmls,)
            elif nc == 1:
                vals = tuple((v,) for v in vals)
                fmls = tuple((f,) for f in fmls)
            for i in range(nr):
                for j in range(nc):
                    v, f = vals[i][j], fmls[i][j]
                    if (v is None or v == '') and (f is None or f == ''):
                        continue
                    cell = ws.Cells(r1 + i, c1 + j)
                    s['cells'].append({
                        'addr': a1(r1 + i, c1 + j), 'row': r1 + i, 'col': c1 + j,
                        'formula': f if isinstance(f, str) and f.startswith('=') else None,
                        'value': (str(v) if v is not None else None),
                        'numfmt': cell.NumberFormatLocal,
                    })
        except Exception as e:
            s['cellsErr'] = str(e)

        try:
            seen = set()
            for cell in ur:
                if cell.MergeCells:
                    ad = addr_of(cell.MergeArea)
                    if ad not in seen:
                        seen.add(ad)
                        s['merged'].append(ad)
        except Exception as e:
            s['mergedErr'] = str(e)

        try:
            for sh in ws.Shapes:
                d = {'name': sh.Name, 'type': int(sh.Type),
                     'left': round(sh.Left, 1), 'top': round(sh.Top, 1),
                     'width': round(sh.Width, 1), 'height': round(sh.Height, 1)}
                for key, fn in (('topLeftCell', lambda: addr_of(sh.TopLeftCell)),
                                ('altText', lambda: sh.AlternativeText),
                                ('text', lambda: sh.TextFrame.Characters().Text),
                                ('onAction', lambda: sh.OnAction)):
                    try:
                        d[key] = fn()
                    except Exception:
                        pass
                try:
                    fc = sh.ControlFormat
                    cf = {}
                    for k in ('Value', 'Min', 'Max', 'SmallChange', 'LargeChange',
                              'LinkedCell', 'ListFillRange'):
                        try:
                            cf[k] = getattr(fc, k)
                        except Exception:
                            pass
                    d['ctrlFormat'] = cf
                except Exception:
                    pass
                try:
                    d['ole'] = {'progid': sh.OLEFormat.ProgId}
                    ole = sh.OLEFormat.Object
                    for k in ('Name', 'LinkedCell', 'ListFillRange'):
                        try:
                            d['ole'][k] = getattr(ole, k)
                        except Exception:
                            pass
                    try:
                        d['ole']['Caption'] = ole.Object.Caption
                    except Exception:
                        pass
                except Exception:
                    pass
                s['shapes'].append(d)
        except Exception as e:
            s['shapesErr'] = str(e)

        try:
            for cell in ur:
                try:
                    t = int(cell.Validation.Type)
                except Exception:
                    continue
                s['validations'].append({'addr': a1(cell.Row, cell.Column), 'type': t,
                                         'f1': cell.Validation.Formula1,
                                         'f2': cell.Validation.Formula2})
        except Exception:
            pass
        try:
            for cell in ur:
                fc = cell.FormatConditions
                if fc.Count:
                    for k in range(1, fc.Count + 1):
                        it = fc.Item(k)
                        try:
                            s['condformats'].append({'addr': a1(cell.Row, cell.Column),
                                                     'type': int(it.Type),
                                                     'f1': getattr(it, 'Formula1', None),
                                                     'appliesTo': addr_of(it.AppliesTo)})
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            for j in range(nc):
                s['colwidths'][a1(1, c1 + j)[:-1]] = round(ws.Columns(c1 + j).ColumnWidth, 2)
            for i in range(nr):
                s['rowheights'][str(r1 + i)] = round(ws.Rows(r1 + i).RowHeight, 1)
        except Exception:
            pass

        doc['sheets'].append(s)
finally:
    wb.Close(SaveChanges=False)
    xl.Quit()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print('written', OUT)
