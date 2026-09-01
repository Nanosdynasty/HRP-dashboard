from major_port_weather import (
    parse_bom_xml,
    parse_canada_feature,
    parse_jma_forecast,
    parse_metno_forecast,
    parse_noaa_grid,
)


def test_metno_forecast_maps_global_port_and_converts_wind():
    payload = {"properties": {
        "meta": {"updated_at": "2026-08-27T08:00:00Z"},
        "timeseries": [{
            "time": "2026-08-27T12:00:00Z",
            "data": {
                "instant": {"details": {
                    "air_temperature": 18.2, "relative_humidity": 77,
                    "wind_speed": 10, "wind_speed_of_gust": 14,
                    "wind_from_direction": 225,
                }},
                "next_6_hours": {
                    "summary": {"symbol_code": "rainshowers_day"},
                    "details": {"precipitation_amount": 2.4},
                },
            },
        }],
    }}
    row = parse_metno_forecast("Rotterdam", payload)[0]
    assert row["provider"] == "MET Norway"
    assert row["region"] == "Europe"
    assert row["weather_condition"] == "Rainshowers"
    assert row["wind_speed_max_kn"] == 19.4
    assert row["wind_direction_from"] == "Southwest"
    assert row["rainfall_mm"] == 2.4
    assert row["wave_height_max_m"] is None


def test_bom_coastal_xml_maps_pilbara_ports_and_waves():
    xml = """<product><amoc><issue-time-utc>2026-08-27T05:01:00Z</issue-time-utc></amoc><forecast>
    <area aac="WA_MW003" description="Pilbara Coast East: Wallal to Cape Preston" type="coast">
      <forecast-period start-time-utc="2026-08-27T05:00:00Z" end-time-utc="2026-08-28T16:00:00Z">
        <text type="forecast_winds">Southwesterly 15 to 20 knots.</text>
        <text type="forecast_seas">1 to 1.5 metres.</text>
        <text type="forecast_swell1">Westerly 2 to 3 metres.</text>
        <text type="forecast_weather">Partly cloudy.</text>
      </forecast-period>
    </area></forecast></product>"""
    rows = parse_bom_xml(xml, "https://www.bom.gov.au/fwo/IDW11120.xml")
    assert {row["location_name"] for row in rows} == {"Port Hedland", "Cape Lambert"}
    assert rows[0]["wind_speed_max_kn"] == 20
    assert rows[0]["wave_height_max_m"] == 3
    assert rows[0]["provider"] == "Australian Bureau of Meteorology"


def test_jma_forecast_maps_major_port_and_translates_to_english():
    payload = [{
        "reportDatetime": "2026-08-27T11:00:00+09:00",
        "timeSeries": [{
            "timeDefines": ["2026-08-27T11:00:00+09:00", "2026-08-28T00:00:00+09:00"],
            "areas": [{
                "area": {"name": "東京地方", "code": "130010"},
                "weatherCodes": ["202", "100"],
                "weathers": ["くもり　時々　雨", "晴れ"],
                "winds": ["北東の風", "南の風"],
                "waves": ["２．５メートル", "１．５メートル"],
            }],
        }],
    }]
    rows = parse_jma_forecast(payload, "130000")
    assert {row["location_name"] for row in rows} == {"Tokyo / Yokohama / Chiba"}
    assert rows[0]["wave_height_max_m"] == 2.5
    assert rows[0]["weather_condition"] == "Rain"
    assert "くもり" not in rows[0]["weather_description"]


def test_noaa_grid_maps_forecast_values_and_alert():
    payload = {"properties": {
        "@id": "https://api.weather.gov/gridpoints/HGX/85,75",
        "gridId": "HGX", "updateTime": "2026-08-27T00:46:19+00:00",
        "windSpeed": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 18.52}]},
        "windDirection": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 180}]},
        "windGust": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 27.78}]},
        "waveHeight": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 1.5}]},
        "temperature": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 30}]},
        "relativeHumidity": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 75}]},
        "visibility": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/P3650D", "value": 10000}]},
        "weather": {"values": []},
    }}
    alerts = {"features": [{"properties": {"event": "Small Craft Advisory"}}]}
    rows = parse_noaa_grid("Houston / Galveston", payload, alerts)
    assert len(rows) == 7
    assert rows[0]["wind_speed_max_kn"] == 10
    assert rows[0]["wave_height_max_m"] == 1.5
    assert rows[0]["warning_description"] == "Small Craft Advisory"


def test_environment_canada_feature_includes_warning_and_extended_forecast():
    feature = {"properties": {
        "lastUpdated": "2026-08-27T04:25:39Z",
        "area": {"value": {"en": "Strait of Georgia"}},
        "regularForecast": {
            "issuedDatetimeUTC": "2026-08-27T04:30:00Z",
            "locations": [{"weatherCondition": {
                "weatherVisibility": {"en": "Showers and fog patches."},
                "wind": {"en": "Wind southeast 15 to 25 knots."},
            }}],
        },
        "waveForecast": {"locations": [{"weatherCondition": {"textSummary": {"en": "Seas 1 to 2 metres."}}}]},
        "extendedForecast": {"locations": [{"weatherCondition": {"forecastPeriods": [
            {"name": {"en": "Friday"}, "value": {"en": "Wind northwest 15 knots."}}
        ]}}]},
        "warnings": {"locations": [{"events": [{
            "name": {"en": "Strong wind warning"}, "status": {"en": "IN EFFECT"}
        }]}]},
    }}
    row = parse_canada_feature("Vancouver", feature)[0]
    assert row["wind_speed_max_kn"] == 25
    assert row["wave_height_max_m"] == 2
    assert row["warning_description"] == "Strong wind warning"
    assert "Friday" in row["forecast_72h"]
