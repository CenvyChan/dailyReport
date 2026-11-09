"""只读核验：生产快照的在线页、Excel、PDF 是否都已经显示申请人。"""
import io
import sys

import django

django.setup()

from django.template.loader import render_to_string  # noqa: E402

from integrations.models import PaymentReportSnapshot  # noqa: E402
from integrations.services.payment_excel import export_payment_excel_bytes  # noqa: E402
from integrations.services.payment_snapshot import render_payment_snapshot_pdf  # noqa: E402
from integrations.services.payment_summary import payment_context  # noqa: E402


def main(snapshot_id):
    snapshot = PaymentReportSnapshot.objects.get(pk=snapshot_id)
    context = payment_context(snapshot)
    html = render_to_string("integrations/payment_snapshot_public.html", context)
    names = [d["originator"] for d in context["details"]]
    print(f"snapshot #{snapshot.pk} {snapshot.company.code} {snapshot.report_type} {snapshot.period_label}")
    print(f"details={len(names)} empty_originator={sum(1 for n in names if not n)}")
    print("sample:", [n for n in names if n][:5])
    print("html_contains_first_name:", (names[0] in html) if names else None)

    period = {
        "label": snapshot.period_label,
        "start_date": snapshot.period_start,
        "end_date": snapshot.period_end,
    }
    book = export_payment_excel_bytes(snapshot.data, period)
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(book))
    ws = wb["详细清单"]
    header = [c.value for c in ws[1]]
    idx = header.index("申请人")
    values = [row[idx] for row in ws.iter_rows(min_row=2, values_only=True)]
    print(f"excel_rows={len(values)} empty={sum(1 for v in values if not v)} sample={[v for v in values if v][:5]}")
    wb.close()

    pdf = render_payment_snapshot_pdf(snapshot)
    print(f"pdf_bytes={len(pdf)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
