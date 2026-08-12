# -*- coding: utf-8 -*-
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
SRC = str(ROOT / 'data' / 'source' / 'demo.xls')
DUMPS = ROOT / 'tools' / 'xls_reverse' / 'dumps'

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible=False; xl.DisplayAlerts=False
out=[]
try:
    wb = xl.Workbooks.Open(SRC, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    for ws in wb.Worksheets:
        n=int(ws.Shapes.Count)
        if n==0: continue
        out.append(f'--- {ws.Name} ({n} shapes) ---')
        for i in range(1,n+1):
            sh=ws.Shapes.Item(i)
            nm=sh.Name; tp=sh.Type
            cap=''
            try: cap=sh.TextFrame.Characters.Caption
            except: pass
            oa=''
            try: oa=sh.OnAction
            except: pass
            r1=c1=r2=c2=''
            try:
                r1=sh.TopLeftCell.Row; c1=sh.TopLeftCell.Column
                r2=sh.BottomRightCell.Row; c2=sh.BottomRightCell.Column
            except: pass
            out.append(f'  [{i}] name={nm!r} type={tp} caption={cap!r} onAction={oa!r} cells={c1}:{r1}-{c2}:{r2}')
    wb.Close(SaveChanges=False)
finally:
    xl.Quit()
(DUMPS / 'btn_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
