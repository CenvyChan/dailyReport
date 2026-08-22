# -*- coding: utf-8 -*-
"""把动态日报表逻辑注入指定工作簿。

用法:
  python inject_dynamic_report.py demo        # 采购入库日报表
  python inject_dynamic_report.py saledemo    # 销售出库日报表

流程：
1. 用 dailyreport.bas.tmpl 按目标配置生成模块源码，导入为 modDailyReport
2. 把 Worksheet_Change / Worksheet_Activate 写入日报表所在的类模块
3. 跑一次 RefreshDailyReport，让明细区从固定行数收敛到实际条目数
4. 保存（VBA 工程已解锁，保存不会重新产生口令）
"""
import os
import shutil
import sys

import win32com.client as win32

SRC_DIR = os.path.dirname(os.path.abspath(__file__)) + r'\vba_src'
TMPL = os.path.join(SRC_DIR, 'dailyreport.bas.tmpl')
EVENTS = os.path.join(SRC_DIR, 'Sheet4_events.txt')
MOD_NAME = 'modDailyReport'
ANSI = 'gbk'  # 本机 ANSI 代码页；VBE 的 Import/AddFromFile 按 ANSI 读文件

TARGETS = {
    'demo': {
        'path': r'E:\DEV\dailyReport\outputs\temp\demo.xls',
        'code_name': 'Sheet4',
        'vars': {
            'REP_SHEET': '采购入库日报表',
            'CAT_L': '人民币',
            'CAT_N': '美金',
            'EMPTY_MSG': '当日无入库明细',
        },
    },
    'saledemo': {
        'path': r'E:\DEV\dailyReport\outputs\saledemo\saledemo.xls',
        'code_name': 'Sheet4',
        'vars': {
            'REP_SHEET': '销售出库日报表',
            'CAT_L': '内销',
            'CAT_N': '外销',
            'EMPTY_MSG': '当日无出库明细',
        },
    },
}


def render(cfg):
    """套模板 -> 写成 ANSI 临时 .bas 供 VBE 导入。"""
    with open(TMPL, encoding='utf-8') as f:
        text = f.read()
    for key, val in cfg['vars'].items():
        text = text.replace('{{%s}}' % key, val)
    left = [ln for ln in text.splitlines() if '{{' in ln]
    if left:
        raise SystemExit('模板仍有未替换的占位符:\n' + '\n'.join(left))
    out = os.path.join(SRC_DIR, '_render.bas')
    with open(out, 'w', encoding=ANSI, newline='\r\n') as f:
        f.write(text)
    return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        raise SystemExit(__doc__)
    key = sys.argv[1]
    cfg = TARGETS[key]
    xls = cfg['path']
    bas = render(cfg)
    with open(EVENTS, encoding='utf-8') as f:
        events_code = f.read()

    shutil.copy2(xls, xls + '.prepatch.bak')

    xl = win32.gencache.EnsureDispatch('Excel.Application')
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.EnableEvents = False
    # 必须允许宏才能 Application.Run；两个工作簿都没有 Workbook_Open/Auto_Open，
    # 且 EnableEvents=False，旧的 SelectionChange 事件不会被触发
    xl.AutomationSecurity = 1
    wb = xl.Workbooks.Open(xls)
    try:
        vbp = wb.VBProject
        print(f'[{key}] {xls}')
        print('VBProject.Protection =', vbp.Protection, '(0=未保护)')

        for comp in list(vbp.VBComponents):
            if comp.Name == MOD_NAME:
                print(f'删除已存在的 {MOD_NAME}')
                vbp.VBComponents.Remove(comp)
        vbp.VBComponents.Import(bas)
        print(f'已导入 {MOD_NAME}（{cfg["vars"]["REP_SHEET"]}）')

        cm = vbp.VBComponents(cfg['code_name']).CodeModule
        if cm.CountOfLines:
            cm.DeleteLines(1, cm.CountOfLines)
        cm.AddFromString(events_code)
        print(f'{cfg["code_name"]} 类模块写入 {cm.CountOfLines} 行')

        xl.Run('RefreshDailyReport')
        print('RefreshDailyReport 已执行')

        wb.Save()
        print('已保存', xls)
    finally:
        wb.Close(False)
        xl.Quit()
        if os.path.exists(bas):
            os.remove(bas)


if __name__ == '__main__':
    sys.exit(main())
