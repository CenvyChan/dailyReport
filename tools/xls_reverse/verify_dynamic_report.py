# -*- coding: utf-8 -*-
"""实测验证动态日报表。

用法:
  python verify_dynamic_report.py demo
  python verify_dynamic_report.py saledemo [--all]

对每个抽样日期：切日期 -> 校验明细行数 == 当日条目数、无空白明细行、
三行汇总数值与 Python 独立算出的期望值一致。
另外校验旋转按钮 OnAction 已挂上，以及数据表内容一次都没被改动。
"""
import collections
import datetime
import hashlib
import random
import sys

import win32com.client as win32

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
from inject_dynamic_report import TARGETS

DETAIL_START = 6
EPOCH = datetime.datetime(1899, 12, 30)   # Excel 序列号 1 = 1900/1/1


def num(v):
    """Excel 求和口径：数值算，文本一律不算（返回 None）。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def ymd(serial):
    """Value2 读出来的日期是序列号，还原成 (年, 月, 日)。"""
    if not isinstance(serial, (int, float)) or isinstance(serial, bool) or serial < 1:
        return None
    d = EPOCH + datetime.timedelta(days=float(serial))
    return (d.year, d.month, d.day)


def detail_count(ws):
    """明细行数 = 「合计」行行号 - 明细起始行"""
    for r in range(DETAIL_START, DETAIL_START + 400):
        if '合计' in str(ws.Cells(r, 1).Formula):
            return r - DETAIL_START
    return -1


def data_fingerprint(wd, last):
    """数据表 A1:F{last} 的指纹，用来证明报表刷新没碰源数据。"""
    vals = wd.Range(wd.Cells(1, 1), wd.Cells(last, 6)).Value2
    blob = repr(vals).encode('utf-8', 'replace')
    return hashlib.sha256(blob).hexdigest()[:16]


def pick_dates(cnt, want_all):
    """抽样：条目最多/最少的日期、每年每月各取一天、若干随机日，再加两个无数据日。"""
    days = sorted(cnt)
    if want_all:
        return days
    by_count = sorted(cnt.items(), key=lambda kv: kv[1])
    picked = {by_count[0][0], by_count[-1][0], days[0], days[-1]}
    picked |= {d for d, _ in by_count[:3]} | {d for d, _ in by_count[-3:]}
    seen_month = set()
    for d in days:                       # 每个自然月取第一天
        if (d[0], d[1]) not in seen_month:
            seen_month.add((d[0], d[1]))
            picked.add(d)
    random.seed(20260813)
    picked |= set(random.sample(days, min(10, len(days))))
    # 两个数据表里没有的日期，验「无明细」分支
    for y, m, dd in ((days[-1][0], days[-1][1], 28), (days[-1][0], days[-1][1], 2)):
        if (y, m, dd) not in cnt:
            picked.add((y, m, dd))
    return sorted(picked)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        raise SystemExit(__doc__)
    cfg = TARGETS[sys.argv[1]]
    want_all = '--all' in sys.argv
    rep_name = cfg['vars']['REP_SHEET']
    cat_l, cat_n = cfg['vars']['CAT_L'], cfg['vars']['CAT_N']

    xl = win32.gencache.EnsureDispatch('Excel.Application')
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.AutomationSecurity = 1
    xl.EnableEvents = True
    wb = xl.Workbooks.Open(cfg['path'])
    ws = wb.Worksheets(rep_name)
    wd = wb.Worksheets('数据表')
    fails = []
    try:
        # 数据表带自动筛选，End(xlUp) 会停在最后一个可见格，必须用 UsedRange
        last = wd.UsedRange.Row + wd.UsedRange.Rows.Count - 1
        rows = wd.Range(wd.Cells(2, 1), wd.Cells(last, 6)).Value2
        src = [(r[0], r[1], r[2], ymd(r[3]), r[4], r[5]) for r in rows]
        src = [r for r in src if r[3] is not None]
        fp0 = data_fingerprint(wd, last)
        cnt = collections.Counter(r[3] for r in src)
        nonnum = [(i, r) for i, r in enumerate(rows, start=2)
                  if num(r[4]) is None or num(r[5]) is None]
        print(f'[{sys.argv[1]}] {rep_name}  源数据 {len(src)} 条 / '
              f'{len(cnt)} 个日期  指纹 {fp0}')
        if nonnum:
            print(f'  注意：数据表有 {len(nonnum)} 行的数量/金额是文本，'
                  f'Excel 求和会跳过 -> 行 {[i for i, _ in nonnum]}')

        cases = pick_dates(cnt, want_all)
        print(f'抽样 {len(cases)} 个日期\n')
        for y, m, d in cases:
            ws.Range('C2').Value = y
            ws.Range('F2').Value = m
            ws.Range('I2').Value = d          # 触发 Worksheet_Change
            xl.CalculateFullRebuild()

            exp = [r for r in src if r[3] == (y, m, d)]
            mon = [r for r in src if r[3][:2] == (y, m)]
            cum = [r for r in mon if r[3][2] <= d]
            sum_row = DETAIL_START + detail_count(ws)
            n_rows = sum_row - DETAIL_START
            blanks = [r for r in range(DETAIL_START, sum_row)
                      if str(ws.Cells(r, 2).Text).strip() == '']

            checks = [('行数', n_rows, max(len(exp), 1))]
            if exp:   # 明细逐行比对名称/数量/类别
                for i, e in enumerate(exp):
                    r = DETAIL_START + i
                    checks.append((f'R{r}名称', str(ws.Cells(r, 2).Value2), str(e[0])))
                    checks.append((f'R{r}数量', ws.Cells(r, 6).Value2, e[4]))
                    checks.append((f'R{r}类别', str(ws.Cells(r, 10).Value2), str(e[2])))
            for label, off, rowsrc in (('当日', 0, exp), ('累计', 1, cum), ('月计', 2, mon)):
                checks.append((f'{label}数量', ws.Cells(sum_row + off, 6).Value2,
                               fsum(r[4] for r in rowsrc)))
                checks.append((f'{label}{cat_l}', ws.Cells(sum_row + off, 12).Value2,
                               fsum(r[5] for r in rowsrc if r[2] == cat_l)))
                checks.append((f'{label}{cat_n}', ws.Cells(sum_row + off, 14).Value2,
                               fsum(r[5] for r in rowsrc if r[2] == cat_n)))

            bad = [c for c in checks if not eq(c[1], c[2])]
            if blanks:
                bad.append(('空白明细行', blanks, []))
            status = 'OK' if not bad else '**FAIL**'
            print(f'  {y}/{m}/{d}: 明细 {n_rows} 行(期望 {max(len(exp),1)})  {status}')
            for label, got, want in bad[:6]:
                print(f'      {label}: 实际 {got!r} 期望 {want!r}')
            if bad:
                fails.append((y, m, d, bad))

        print('\n=== 旋转按钮 OnAction ===')
        for shp in ws.Shapes:
            try:
                lc = shp.ControlFormat.LinkedCell
            except Exception:
                continue
            ok = shp.OnAction.endswith('RefreshDailyReport')
            print(f'  {shp.Name} LinkedCell={lc} OnAction={shp.OnAction!r} '
                  f'{"OK" if ok else "**FAIL**"}')
            if not ok:
                fails.append(('OnAction', shp.Name))

        fp1 = data_fingerprint(wd, last)
        print(f'\n=== 数据表指纹 ===\n  刷新前 {fp0}\n  刷新后 {fp1}  '
              f'{"未改动 OK" if fp0 == fp1 else "**被改动 FAIL**"}')
        if fp0 != fp1:
            fails.append(('数据表被改动',))

        wb.Save()
        print('\n已保存')
    finally:
        wb.Close(False)
        xl.Quit()

    print(f'\n{"全部通过" if not fails else f"失败 {len(fails)} 项"}')
    return 1 if fails else 0


def fsum(vals):
    """按 Excel 口径求和：文本跳过。"""
    return sum(n for n in (num(v) for v in vals) if n is not None)


def eq(got, want):
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return abs((num(got) or 0) - want) < 1e-6
    return str(got if got is not None else '') == str(want if want is not None else '')


if __name__ == '__main__':
    sys.exit(main())
