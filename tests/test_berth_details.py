from berth_details import berth_detail_for_port


def test_india_dry_bulk_berths_keep_port_scope_and_reported_cargo_use():
    detail = berth_detail_for_port({"name": "Paradip Port", "country": "IN"})
    assert detail is not None
    assert detail["total_berths"] == 24
    assert detail["dry_bulk_berths"] == 6
    by_name = {row["name"].lower(): row for row in detail["berths"]}
    assert by_name["new coal import berth"]["use"] == "Coking coal import"
    assert by_name["coal berth - i"]["use"] == "Thermal coal loading"
    assert all(row["source_url"] for row in detail["berths"])


def test_anchorage_does_not_become_a_berth():
    detail = berth_detail_for_port({"name": "Bedi Port", "country": "IN"})
    assert detail is not None
    assert detail["total_berths"] == 4
    assert all(row["facility_type"] != "anchorage" for row in detail["berths"])


def test_global_terminal_count_is_not_presented_as_whole_port_count():
    detail = berth_detail_for_port({"name": "Richards Bay Coal Terminal", "country": "ZA"})
    assert detail is not None
    assert detail["scope_type"] == "terminal"
    assert detail["total_berths"] == 6
    assert detail["berths"][0]["use"] == "Coal export loading"


def test_port_hedland_selected_groups_and_missing_dry_bulk_total():
    detail = berth_detail_for_port({"name": "Port Hedland", "country": "AU"})
    assert detail is not None
    assert detail["total_berths"] == 19
    assert detail["dry_bulk_berths"] is None
    assert any("Utah Point" in row["name"] for row in detail["berths"])


def test_newcastle_distinguishes_coal_berths_from_port_total():
    detail = berth_detail_for_port({"name": "Newcastle", "country": "AU"})
    assert detail is not None
    assert detail["total_berths"] == 20
    assert detail["dry_bulk_berths"] is None
    assert sum(1 for row in detail["berths"] if "Coal" in row["cargoes"]) == 3


def test_visakhapatnam_alias_and_reported_berth_use():
    detail = berth_detail_for_port({"name": "VISHAKHAPATNAM", "country": "IN"})
    assert detail is not None
    assert detail["total_berths"] == 31
    assert any("coal import" in row["use"].lower() for row in detail["berths"])
