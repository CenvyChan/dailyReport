# -*- coding: utf-8 -*-
"""Extract UserForm1 designer object info and sheet buttons via Excel COM."""
import os, sys, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import win32com.client

ROOT = pathlib.Path(__file__).parent.parent.parent
SRC = str(ROOT / 'data' / 'source' / 'demo.xls')
DUMPS = ROOT / 'tools' / 'xls_reverse' / 'dumps'

xl = win32com.client.Dispatch('Excel.Application')
xl.Visible = False
xl.DisplayAlerts = False
out=[]
try:
    wb = xl.Workbooks.Open(SRC, ReadOnly=True, IgnoreReadOnlyRecommended=True)
    for ws in wb.Worksheets:
        out.append(f'--- Sheet {ws.Name} shapes ---')
        try:
            shc = int(ws.Shapes.Count)
        except Exception:
            shc = 0
        out.append(f'  shapes count: {shc}')
        for i in range(1, shc+1):
            try:
                sh = ws.Shapes.Item(i)
                name = sh.Name
                typ = sh.Type
                tl = sh.TopLeftCell.Address(False,False)
                br = sh.BottomRightCell.Address(False,False)
                onaction = ''
                try: onaction = sh.OnAction
                except Exception: pass
                cap = ''
                try:
                    tff = sh.TextFrame
                    cap = tff.Characters.Caption
                except Exception:
                    try: cap = sh.TextFrame2.TextRange.Text
                    except Exception: pass
                out.append(f'  shape[{i}] name={name!r} type={typ} caption={cap!r} range={tl}:{br} onAction={onaction!r}')
            except Exception as e:
                out.append(f'  shape[{i}] err {repr(e)}')
    out.append('')

    out.append('--- VBA Project components ---')
    try:
        vbp = wb.VBProject
        for vbc in vbp.VBComponents:
            out.append(f'  comp: {vbc.Name}  type={vbc.Type}  codeName=?')
            if vbc.Type == 3:
                try:
                    props = vbc.Properties
                    out.append(f'    form Caption={props("Caption").Value!r}  Width={props("Width").Value} Height={props("Height").Value}')
                except Exception as e:
                    out.append(f'    form props err: {e}')
                try:
                    ctrl = vbc.Designer.Controls
                    for j in range(1, ctrl.Count+1):
                        c = ctrl(j)
                        try: cap = c.Caption
                        except: cap = ''
                        try: ml = c.MultiSelect
                        except: ml=None
                        out.append(f'    ctrl[{j}] name={c.Name!r} caption={cap!r} L={c.Left} T={c.Top} W={c.Width} H={c.Height} multiselect={ml}')
                except Exception as e:
                    out.append(f'    controls err: {e}')
    except Exception as e:
        out.append(f'  VBProject access err: {e}  (VBE project is password-protected)')

    wb.Close(SaveChanges=False)
finally:
    xl.Quit()

(DUMPS / 'form_dump.txt').write_text('\n'.join(out), encoding='utf-8')
print('\n'.join(out))
