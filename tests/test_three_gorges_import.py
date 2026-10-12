"""Monthly imports must be complete and preserve unrelated observations."""
import io
import json
import sys
import zipfile
from unittest.mock import patch

import pytest

from scripts.refresh_three_gorges import main, table_rows


def monthly_docx(days):
    rows = []
    for day in days:
        cells = "".join(f"<w:tc><w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:tc>"
                        for value in (day, "157.33", "42.77", "18000", "15000"))
        rows.append(f"<w:tr>{cells}</w:tr>")
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:tbl>' + "".join(rows) + '</w:tbl></w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_complete_month_preserves_values_and_year():
    rows = table_rows(monthly_docx(range(1, 32)), "August 2026", None, "august-2026.docx")
    assert len(rows) == 31
    assert rows[-1]["date"] == "2026-08-31"
    assert rows[-1]["downstream_level_m"] == 42.77
    assert rows[-1]["inflow_m3s"] == 18000
    assert rows[-1]["source_url"] is None
    assert table_rows(monthly_docx(range(1, 32)), "August 2027", None)[-1]["date"] == "2027-08-31"


def test_duplicate_date_does_not_disguise_missing_day():
    with pytest.raises(ValueError, match="distinct daily"):
        table_rows(monthly_docx(list(range(1, 31)) + [30]), "August 2026", None)


def test_local_import_is_idempotent_and_preserves_other_months(tmp_path):
    source = tmp_path / "august-2026.docx"
    source.write_bytes(monthly_docx(range(1, 32)))
    target = tmp_path / "data.json"
    old_rows = [{"date": "2026-07-31", "source_month": "July 2026"},
                {"date": "2026-09-01", "source_month": "September 2026"}]
    target.write_text(json.dumps({"observations": old_rows, "monthly_coverage": [],
                                 "known_gaps": []}), encoding="utf-8")
    argv = ["refresh", "--data", str(target), "--source-docx", str(source),
            "--source-month", "August 2026"]
    with patch.object(sys, "argv", argv):
        main()
        main()
    result = json.loads(target.read_text(encoding="utf-8"))
    assert len(result["observations"]) == 33
    assert result["observations"][0] == old_rows[0]
    assert result["observations"][-1] == old_rows[1]
    assert result["coverage_end"] == "2026-09-01"
    assert len(result["monthly_coverage"]) == 1
    assert result["monthly_coverage"][0]["missing_days"] == 0
    assert result["monthly_coverage"][0]["source_document_sha256"]
    prior = target.read_bytes()
    source.write_bytes(monthly_docx(range(1, 31)))
    with patch.object(sys, "argv", argv), pytest.raises(ValueError):
        main()
    assert target.read_bytes() == prior
