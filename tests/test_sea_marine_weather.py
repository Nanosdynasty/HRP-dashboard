import unittest

from sea_marine_weather import (
    parse_met_shipping,
    parse_nchmf_sea,
    parse_nmc_offshore,
    parse_nmc_coastal,
    merge_china_port_forecasts,
    parse_pagasa_gale,
    parse_singapore,
    parse_tmd_shipping,
)


class SeaMarineWeatherParserTests(unittest.TestCase):
    def test_metmalaysia_port_mapping_and_units(self):
        page = """<table><tr><td>05/08/2026<br>Wednesday</td>
        <td>Isolated thunderstorms</td><td><strong>Wind Direction:</strong> SW<br>
        <strong>Wind Speed:</strong> 40-50km/h<br><strong>Wave Height:</strong> 2.5-3.5 m</td></tr></table>"""
        rows = parse_met_shipping("Sh003", "Southern Straits of Melaka", page)
        self.assertEqual({row["location_name"] for row in rows}, {"Port Klang", "Tanjung Pelepas"})
        self.assertEqual(rows[0]["wave_height_max_m"], 3.5)
        self.assertAlmostEqual(rows[0]["wind_speed_max_kn"], 27.0)
        self.assertIn("area forecast", rows[0]["forecast_basis"].lower())

    def test_tmd_shipping_maps_gulf_ports(self):
        page = """<p class="text-announcementdate">Announcement Date 05 August 2026 13:00</p>
        <p class="ship-forecast-title">The Gulf of Thailand</p>
        <p class="ship-forecast-description">Fairly widespread thundershowers. Southwesterly winds 11-18 knots.
        Wave height about 2 meters and above 2 meters in thundershowers.</p>"""
        rows = parse_tmd_shipping(page)
        self.assertIn("Laem Chabang", {row["location_name"] for row in rows})
        self.assertEqual(rows[0]["wind_speed_max_kn"], 18.0)

    def test_pagasa_gale_maps_named_seaboard(self):
        page = """<h5>Issued at: 5:00 AM, 05 August 2026</h5>
        <p>Strong to gale-force winds associated with tropical cyclone Maymay</p><table><tr>
        <td><b>THE WESTERN SEABOARD OF NORTHERN LUZON</b> (Zambales)</td><td>Stormy</td>
        <td>(45-63) / (24-34)</td><td>Rough to very rough</td><td>2.8-4.5 m</td></tr></table>"""
        rows = parse_pagasa_gale(page)
        self.assertEqual({row["location_name"] for row in rows}, {"Manila", "Subic Bay"})
        self.assertTrue(all(row["warning_description"] for row in rows))
        self.assertIn("tropical cyclone", rows[0]["warning_description"].lower())

    def test_singapore_official_api_normalization(self):
        payload = {"data": {"records": [{
            "updatedTimestamp": "2026-08-05T06:00:00+08:00",
            "periods": [{"start": "2026-08-05T06:00:00+08:00", "end": "2026-08-05T18:00:00+08:00", "regions": {"south": "Thundery Showers"}}],
            "general": {"wind": {"direction": "SSW", "speed": {"low": 15, "high": 30}}, "temperature": {"low": 25, "high": 33}, "relativeHumidity": {"low": 60, "high": 95}},
        }]}}
        rows = parse_singapore(payload)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["country"], "Singapore")
        self.assertEqual(rows[0]["temperature_max_c"], 33)

    def test_china_nmc_offshore_maps_ports_and_translates_fields(self):
        page = '''<div class=author>2026年08月05日14时</div><table><tbody>
        <tr name="渤海"><td rowspan=2>渤海</td><td>00-12</td><td>小雨</td><td>东北风</td><td>5～6</td><td>2.5</td><td>6</td></tr>
        <tr name="渤海"><td>12-24</td><td>多云</td><td>北风</td><td>4～5</td><td>1.0</td><td>8</td></tr>
        </tbody></table>'''
        rows = parse_nmc_offshore(page)
        self.assertEqual({row["location_name"] for row in rows}, {"Tianjin", "Qinhuangdao", "Caofeidian"})
        self.assertTrue(all(row["country"] == "China" for row in rows))
        self.assertEqual(rows[0]["weather_condition"], "Light rain")
        self.assertEqual(rows[0]["wind_direction_from"], "Northeast")

    def test_china_nmc_coastal_maps_dry_bulk_ports_and_risk(self):
        page = '''<div class=author>2026年08月11日14时</div><table><tbody>
        <tr name="唐山沿岸"><td rowspan=2>唐山沿岸</td><td>00-12</td><td>雷阵雨</td><td>东北风</td><td>6～7</td><td>4</td></tr>
        <tr name="唐山沿岸"><td>12-24</td><td>小雨</td><td>北风</td><td>4～5</td><td>10</td></tr>
        </tbody></table>'''
        rows = parse_nmc_coastal(page)
        self.assertEqual({row["location_name"] for row in rows}, {"Caofeidian", "Jingtang"})
        first = next(row for row in rows if row["location_name"] == "Caofeidian" and row["weather_condition"] == "Thundershowers")
        self.assertEqual(first["visibility_source"], 4.0)
        self.assertEqual(first["weather_risk_level"], "High")
        self.assertIn("loading", " ".join(first["operational_impacts"]).lower())

    def test_china_coastal_forecast_is_enriched_with_offshore_wave(self):
        offshore = [{
            "location_name": "Caofeidian", "location_id": "cma-port-caofeidian",
            "valid_from": "2026-08-11T14:00:00+08:00", "valid_to": "2026-08-12T02:00:00+08:00",
            "marine_area": "Bohai Sea", "wave_height_min_m": 2.5, "wave_height_max_m": 2.5,
        }]
        coastal = [{
            "location_name": "Caofeidian", "location_id": "cma-port-caofeidian",
            "valid_from": "2026-08-11T14:00:00+08:00", "valid_to": "2026-08-12T02:00:00+08:00",
            "marine_area": "Tangshan coast", "weather_condition": "Light rain",
            "wind_speed_max_kn": 21.0, "visibility_source": 10.0,
        }]
        rows = merge_china_port_forecasts(offshore, coastal)
        self.assertEqual(rows[0]["wave_height_max_m"], 2.5)
        self.assertEqual(rows[0]["offshore_marine_area"], "Bohai Sea")
        self.assertEqual(rows[0]["weather_risk_level"], "Moderate")

    def test_vietnam_nchmf_maps_ports_with_english_summary(self):
        page = '''<caption>SEA WEATHER - Day and night 05/08/2026</caption>
        <a href="#">Lâm Đồng đến Cà Mau</a><p>Có mưa rào và dông rải rác.<br />
        Tầm nhìn xa : Trên 10km.<br />Gió tây nam cấp 5-6. Sóng cao 1,5 - 2,5m.</p>'''
        rows = parse_nchmf_sea(page)
        self.assertEqual({row["location_name"] for row in rows}, {"Vung Tau", "Cai Mep", "Ho Chi Minh City"})
        self.assertTrue(all(row["country"] == "Vietnam" for row in rows))
        self.assertEqual(rows[0]["weather_condition"], "Showers and thunderstorms")
        self.assertNotIn("Có mưa", rows[0]["weather_description"])


if __name__ == "__main__":
    unittest.main()
