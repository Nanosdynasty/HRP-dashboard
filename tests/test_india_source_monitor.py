from types import SimpleNamespace
import pytest
import india_source_monitor as monitor


def test_coal_parser_reconciles_both_month_and_ytd(monkeypatch):
    text = ('Coal Production\nGrand Total 69.815 64.88 7.61 302.29 300.00 0.763\n'
            'Coal Dispatch\nGrand Total 86.91 73.59 18.10 355.44 350.00 1.554')
    monkeypatch.setattr(monitor, 'PdfReader', lambda _: SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda: text)]))
    # Multiple headings on one page are ambiguous and must never be guessed.
    with pytest.raises(ValueError):
        monitor.parse_checked_coal('2026-07', 'https://coal.gov.in/test.pdf', b'')


def test_report_links_rejects_script_and_deduplicates():
    html = '<a href="javascript:a.pdf">Bad</a><a href="/report.pdf">July</a><a href="/report.pdf">July</a>'
    assert monitor.report_links(html, 'https://coal.gov.in/') == [
        {'title': 'July', 'url': 'https://coal.gov.in/report.pdf'}]


def test_coal_parser_rejects_unreconciled_target(monkeypatch):
    text = 'Coal Production\nGrand Total 57.4 64.88 7.61 302.29 300.00 0.763'
    monkeypatch.setattr(monitor, 'PdfReader', lambda _: SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda: text)]))
    with pytest.raises(ValueError):
        monitor.parse_checked_coal('2026-07', 'https://coal.gov.in/test.pdf', b'')
