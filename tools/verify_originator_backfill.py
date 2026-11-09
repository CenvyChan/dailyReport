"""只读对比：回填前后生产库的审批与快照，确认只改了申请人字段。"""
import json
import sqlite3
import sys

BEFORE = sys.argv[1] if len(sys.argv) > 1 else "/home/mesdev/deploy/daily-report/backups/pre-originator-data-20261109.sqlite3"
AFTER = sys.argv[2] if len(sys.argv) > 2 else "/home/mesdev/deploy/daily-report/data/daily_report.sqlite3"


def load(path):
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    cur = con.cursor()
    cur.execute(
        "select id, company_id, report_type, period_label, period_start, period_end, "
        "process_code, data from integrations_paymentreportsnapshot order by id"
    )
    snaps = {row[0]: row for row in cur.fetchall()}
    cur.execute(
        "select id, company_id, process_instance_id, status, amount, create_time, "
        "title, process_code, process_name from integrations_dingtalkapprovalinstance order by id"
    )
    apps = {row[0]: row for row in cur.fetchall()}
    con.close()
    return snaps, apps


def main():
    before_snaps, before_apps = load(BEFORE)
    after_snaps, after_apps = load(AFTER)
    problems = []
    for sid, before in before_snaps.items():
        after = after_snaps.get(sid)
        if after is None:
            problems.append(("missing", sid))
            continue
        if tuple(before[1:7]) != tuple(after[1:7]):
            problems.append(("identity", sid))
        bd, ad = json.loads(before[7]), json.loads(after[7])
        for detail in (x for g in bd["by_recipient"] for x in g["details"]):
            detail.pop("originator", None)
        for detail in (x for g in ad["by_recipient"] for x in g["details"]):
            detail.pop("originator", None)
        if bd != ad:
            problems.append(("content", sid))
    print("snapshots:", len(before_snaps), "non-originator problems:", problems or "none")
    diffs = [pk for pk, before in before_apps.items() if before[1:] != after_apps[pk][1:]]
    print("approvals:", len(before_apps), "non-name diffs:", len(diffs))
    return 0 if not problems and not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
