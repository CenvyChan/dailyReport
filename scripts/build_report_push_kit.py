"""构建脱敏交接包；只包含明确白名单源码与虚构示例，不复制生产数据。"""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "handoff/report-push-kit"
REFERENCE_FILES = [
    "integrations/services/operations_a2ui.py",
    "integrations/services/a2ui_robot.py",
    "integrations/services/operations_delivery.py",
    "integrations/services/report_delivery.py",
    "integrations/services/snapshot_export.py",
    "integrations/services/reconciliation.py",
    "integrations/services/dingtalk_client.py",
    "integrations/services/payment_a2ui.py",
    "integrations/services/payment_report.py",
    "integrations/services/payment_excel.py",
    "integrations/services/payment_organizations.py",
    "integrations/services/payment_card.py",
    "integrations/services/payment_message.py",
    "integrations/models.py",
    "integrations/admin.py",
    "integrations/crypto.py",
    "integrations/management/commands/send_payment_report.py",
    "integrations/management/commands/send_scheduled_payment_reports.py",
    "integrations/management/commands/generate_and_send_report.py",
    "integrations/migrations/0016_payment_organization_routing.py",
    "integrations/migrations/0017_group_company_selection.py",
    "integrations/migrations/0018_report_delivery_state.py",
    "integrations/tests/test_operations_a2ui.py",
    "integrations/tests/test_report_backfill.py",
    "integrations/tests/test_payment_a2ui.py",
    "integrations/tests/test_payment_organizations.py",
    "integrations/tests/test_payment_delivery.py",
    "core/admin.py",
    "core/services/audit.py",
    "core/tests/test_admin_audit.py",
    "templates/integrations/report_snapshot.html",
    "templates/integrations/report_snapshot_book.html",
    "core/templatetags/display.py",
    "docs/templates/operations_daily_report.a2ui.json",
    "requirements.txt",
    "Dockerfile",
    "docs/templates/payment_application_report.a2ui.json",
    "docs/templates/payment_application_report.a2ui.send-content.json",
    "core/models.py",
    "core/testing.py",
    "core/services/users.py",
    "core/services/companies.py",
    "sales/models.py",
    "purchase/models.py",
    "notifications/models.py",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def included_files():
    return sorted(p for p in KIT.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and p.suffix not in (".pyc", ".pyo") and p.name != "MANIFEST.json")


def main():
    sources = []
    for name in REFERENCE_FILES:
        body = (ROOT / name).read_text(encoding="utf-8")
        sanitized = body.replace("http://172.16.77.77:3288/k3cloud", "https://<KINGDEE_HOST>/k3cloud")
        sanitized = sanitized.replace("172.16.77.80", "<PRODUCTION_HOST>").replace("172.16.77.77", "<KINGDEE_HOST>")
        sanitized = sanitized.replace("cid6vVsD8T971qSRMK+06RykA==", "<EXAMPLE_GROUP_ID>")
        target = KIT / "reference" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sanitized, encoding="utf-8")
        sources.append({"file": "reference/" + name, "source": name,
                        "sanitized": sanitized != body, "sourceSha256": sha(ROOT / name)})
    for name in ("operations_a2ui.py", "a2ui_robot.py"):
        text = (ROOT / "integrations/services" / name).read_text(encoding="utf-8")
        if name == "a2ui_robot.py":
            text = text.replace("from integrations.services.dingtalk_client import DingtalkError", "from .errors import DingtalkError")
        (KIT / "portable" / name).write_text(text, encoding="utf-8")
    (KIT / "portable/operations_daily_report.a2ui.json").write_bytes(
        (ROOT / "docs/templates/operations_daily_report.a2ui.json").read_bytes())
    (KIT / "SOURCE_MAP.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    forbidden = []
    for path in included_files():
        relative = path.relative_to(KIT).as_posix()
        if path.name == ".env" or path.suffix in (".sqlite3", ".sqlite", ".db", ".pem", ".key"):
            forbidden.append(relative)
        if path.suffix.lower() in (".py", ".json", ".md", ".html", ".txt") or path.name == "Dockerfile":
            text = path.read_text(encoding="utf-8")
            patterns = (r"\b172\.16\.\d+\.\d+\b", r"cid6vVsD8T971qSRMK\+06RykA==",
                        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                        r"gAAAAA[A-Za-z0-9_=-]{45,}", r"\bsk-[A-Za-z0-9_-]{24,}")
            if any(re.search(pattern, text) for pattern in patterns):
                forbidden.append(relative)
    assert not forbidden, "Unsafe handoff files: " + repr(forbidden)
    manifest = {"version": "2026-10-28", "purpose": "native-a2ui-report-handoff",
                "credentialsIncluded": False, "businessDataIncluded": False,
                "exampleData": "fictional", "securityScan": "passed",
                "files": [{"path": p.relative_to(KIT).as_posix(), "bytes": p.stat().st_size,
                           "sha256": sha(p)} for p in included_files()]}
    (KIT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    output = ROOT / "handoff/report-push-kit-20261028.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in included_files() + [KIT / "MANIFEST.json"]:
            archive.write(path, "report-push-kit/" + path.relative_to(KIT).as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in archive.namelist())
    print(json.dumps({"archive": str(output), "files": len(manifest["files"]) + 1,
                      "bytes": output.stat().st_size, "sha256": sha(output), "securityScan": "passed"}))


if __name__ == "__main__":
    main()
