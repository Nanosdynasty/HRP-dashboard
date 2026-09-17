# Maritime route-engine knowledge base

Updated: 17 September 2026  
Scope: analytical voyage planning only. It does not replace ECDIS, official charts, the master, or required passage planning.

## What documented maritime route systems do

| Provider / authority | Documented practice | Design adopted here |
| --- | --- | --- |
| Searoutes | Produces shortest feasible sea routes considering traffic-separation schemes and port entries; accepts vessel dimensions/draft, speed, blocked areas, ECA/HRA preferences, and reports crossed areas. | A maritime network is the base path. Zones must never become route legs. |
| Veson Nautical | Uses selectable passages and routing templates, with weather presented as a separate map layer. | Keep passage rules and risk overlays separate from line geometry. |
| Wartsila Navi-Planner | Plans berth-to-berth with chart data, validation, weather/environment/piracy overlays and shore-to-bridge consistency. | Treat route validation and provenance as first-class API outputs. |
| StormGeo | Reassesses against weather, vessel limits and commercial goals, with expert support. | Add dynamic alternatives and human approval only after the static safe path is established. |
| IMO | Defines TSS, recommended tracks, deep-water routes, precautionary areas and areas to avoid. It recognises weather routing as a safety aid. | Integrate official routeing measures as authoritative constraints when licensed source geometry is available. |

## Active policy

1. Generate a route only on the maritime network.
2. Preserve port approach connectors and calculate all displayed distance from the final polyline.
3. Use JWC, piracy-watch and ECA information for exposure reporting. Do not follow a display polygon edge as a vessel track.
4. Permit a replacement only when it is a reviewed, named water-only corridor with its own regression fixture.
5. Return the route profile, policy identifier, zone exposure and warnings with every API response.

This corrects the defect where a coarse JWC display polygon created a route across the Arabian Peninsula.

## Implementation roadmap

- **Completed:** maritime-network-first route selection, retirement of coarse JWC boundary detours, final-polyline distance calculation and regression coverage.
- **Next:** integrate licensed ENC/bathymetry plus official IMO routeing geometry, then reject every route segment that fails the navigational validation layer.
- **Then:** support vessel IMO/draft and route templates, followed by forecast-aware alternatives, fuel/emissions objectives and master/shore approval.

## Source register

- [Searoutes sea-route API](https://developer.searoutes.com/reference/getsearoute)
- [Searoutes route collections](https://developer.searoutes.com/v3.0/reference/searchroutes)
- [Veson routing and weather](https://help.veson.com/vms/maps-routing-and-weather)
- [Wartsila Navi-Planner](https://www.wartsila.com/marine/products/marine-navigation-solutions/navi-planner)
- [StormGeo Voyage Optimization](https://stormgeo.com/products/voyage-optimization)
- [IMO Ships’ Routeing](https://www.imo.org/en/ourwork/safety/pages/shipsrouteing.aspx)