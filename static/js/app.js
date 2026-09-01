const nativeFetch = window.fetch.bind(window);
window.fetch = async function protectedApiFetch(input, init = {}) {
  const method = String(init.method || "GET").toUpperCase();
  const url = typeof input === "string" ? input : input.url;
  const sameOrigin = new URL(url, window.location.href).origin === window.location.origin;
  const options = { ...init };
  if (sameOrigin && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = window.sessionStorage.getItem("hrpAdminToken");
    if (token) {
      options.headers = new Headers(options.headers || {});
      options.headers.set("X-Admin-Token", token);
    }
  }
  let response = await nativeFetch(input, options);
  if (sameOrigin && response.status === 401 && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    const detail = await response.clone().json().catch(() => ({}));
    if (String(detail.detail || "").includes("Administrator token")) {
      const token = window.prompt("Administrator token required for this operation:");
      if (token) {
        window.sessionStorage.setItem("hrpAdminToken", token);
        options.headers = new Headers(options.headers || {});
        options.headers.set("X-Admin-Token", token);
        response = await nativeFetch(input, options);
      }
    }
  }
  return response;
};

const LAYER_CONFIG = {
  coal_plants: { label: "Coal plant", color: "#6f7782", radius: 3, mode: "energy" },
  solar: { label: "Solar power", color: "#e9a823", radius: 2, mode: "energy" },
  wind: { label: "Wind power", color: "#55a6c8", radius: 2, mode: "energy" },
  hydro: { label: "Hydropower", color: "#296fba", radius: 3, mode: "energy" },
  nuclear: { label: "Nuclear power", color: "#8b65b6", radius: 4, mode: "energy" },
  geothermal: { label: "Geothermal", color: "#db5b45", radius: 3, mode: "energy" },
  bioenergy: { label: "Bioenergy", color: "#629c4d", radius: 2, mode: "energy" },
  coal_mines: { label: "Coal mine", color: "#242b38", radius: 3, mode: "commodities" },
  coal_trade_terminals: { label: "Coal trade terminal", color: "#db2f34", radius: 3, mode: "commodities" },
  iron_ore_mines: { label: "Iron ore mine", color: "#a45332", radius: 3, mode: "commodities" },
  iron_ore_terminals: { label: "Iron ore trade terminal", color: "#d67a27", radius: 4.5, mode: "commodities" },
  steel_plants: { label: "Iron & steel plant", color: "#536a7a", radius: 3, mode: "commodities" },
  cement_plants: { label: "Cement plant", color: "#9a8a73", radius: 3, mode: "commodities" }
};

const WORKSPACE_LAYERS = {
  energy: ["coal_plants", "solar", "wind", "hydro", "nuclear", "geothermal", "bioenergy"],
  commodities: ["coal_mines", "coal_trade_terminals", "iron_ore_mines", "iron_ore_terminals", "steel_plants", "cement_plants"]
};

const COAL_ASSET_CONFIG = {
  coal_mines: { label: "Coal mine", color: "#242b38", radius: 3 },
  coal_trade_terminals: { label: "Coal trade terminal", color: "#db2f34", radius: 4 },
  dry_bulk_ports: { label: "Dry-bulk port", color: "#003671", radius: 3 },
  power_consumers: { label: "Coal-fired power plant", color: "#6f7782", radius: 3 },
  steel_consumers: { label: "Steel plant", color: "#536a7a", radius: 3 },
  cement_consumers: { label: "Cement plant", color: "#9a8a73", radius: 3 }
};

const ENGLISH_MAP_LABELS = {
  continents: [
    ["North America", 47, -105],
    ["South America", -18, -59],
    ["Europe", 52, 16],
    ["Africa", 7, 20],
    ["Asia", 43, 88],
    ["Oceania", -24, 135]
  ],
  countries: [
    ["India", 22, 79], ["China", 36, 104], ["Australia", -25, 134],
    ["Indonesia", -3, 118], ["South Africa", -29, 24], ["Brazil", -11, -52],
    ["United States", 39, -99], ["Canada", 58, -107], ["Russia", 61, 94],
    ["Japan", 37, 138], ["South Korea", 36, 128], ["Vietnam", 16, 107],
    ["Bangladesh", 24, 90], ["Pakistan", 30, 69], ["Türkiye", 39, 35],
    ["United Kingdom", 55, -3], ["Germany", 51, 10], ["France", 47, 2],
    ["Spain", 40, -4], ["Italy", 42, 12], ["Egypt", 27, 30],
    ["Saudi Arabia", 24, 45], ["United Arab Emirates", 24, 54],
    ["Colombia", 4, -73], ["Chile", -30, -71], ["Argentina", -38, -64]
  ]
};

const COUNTRY_LABEL_WIDTHS = {
  India: 70, China: 96, Australia: 105, Indonesia: 100,
  "South Africa": 82, Brazil: 95, "United States": 112, Canada: 120,
  Russia: 130, Japan: 48, "South Korea": 48, Vietnam: 45,
  Bangladesh: 45, Pakistan: 62, Türkiye: 60, "United Kingdom": 54,
  Germany: 48, France: 48, Spain: 48, Italy: 38, Egypt: 48,
  "Saudi Arabia": 76, "United Arab Emirates": 55, Colombia: 58,
  Chile: 36, Argentina: 70
};

const MAP_SKINS = {
  light: () => L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 16, attribution: "Tiles &copy; Esri" }
  ),
  nautical: () => L.layerGroup([
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 16,
      attribution: "Ocean basemap &copy; Esri, GEBCO, NOAA"
    }),
    L.tileLayer("https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png", {
      maxZoom: 18,
      opacity: 0.92,
      attribution: "Navigation aids &copy; OpenSeaMap contributors"
    }),
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 16,
      attribution: "English reference labels &copy; Esri"
    })
  ]),
  satellite: () => L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 18, attribution: "Imagery &copy; Esri" }
  ),
  dark: () => L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
    {
      subdomains: "abcd",
      maxZoom: 20,
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
    }
  )
};

const DEFAULT_MAP_CENTER = [23, 90];
const DEFAULT_MAP_ZOOM = 3;
const DEFAULT_AIS_REGIONS = ["india", "china", "gulf", "southeast_asia"];
const AIS_REGION_BOUNDS = {
  india: [[5, 64], [31, 100]],
  china: [[17, 105], [42, 125]],
  gulf: [[12, 42], [31.5, 62.5]],
  southeast_asia: [[-12, 94], [22, 132]],
  japan_korea: [[30, 124], [47, 147]],
  australia: [[-47, 108], [-8, 158]],
  europe_med: [[28, -12], [72, 45]],
  africa: [[-38, -20], [38, 58]],
  north_america: [[5, -170], [72, -50]],
  south_america: [[-58, -92], [15, -30]],
  world: [[-90, -180], [90, 180]]
};

const state = {
  map: null,
  baseLayer: null,
  mapSkin: "light",
  mode: "ports",
  portLayer: null,
  assetLayers: new Map(),
  assetCache: new Map(),
  layerEpoch: new Map(),
  ports: [],
  filteredPorts: [],
  routeLayer: null,
  routeMode: false,
  routePickIndex: 0,
  routePorts: [],
  routePortCatalog: [],
  coalLayer: null,
  aisLayer: null,
  aisTrailLayer: null,
  aisVessels: [],
  aisEnabled: false,
  aisLoading: false,
  aisRefreshTimer: null,
  aisDisplayMode: "all",
  aisTypeFilter: "cargo_tanker",
  aisRegions: new Set(DEFAULT_AIS_REGIONS),
  aisWatchlist: new Map(),
  selectedAisMmsi: null,
  weatherLayer: null,
  weatherSymbolLayer: null,
  coastalWeatherEnabled: false,
  coastalWeatherRows: [],
  coastalWeatherSource: "all",
  coastalWeatherHours: 0,
  coastalWeatherAnimated: true,
  coastalWeatherPolygonsVisible: false,
  coastalWeatherParameters: new Set(["rain", "wind", "wave", "warning", "cyclone"]),
  coastalWeatherView: "map",
  coastalWeatherLocationType: "all",
  coastalWeatherDataClass: "all",
  coastalWeatherPortStatus: "all",
  coastalWeatherQuery: "",
  coastalWeatherLoading: false,
  coastalWeatherPendingReload: false,
  portDisruptions: null,
  weatherPortTierCache: new Map(),
  riverLayer: null,
  riverRows: [],
  riverSources: [],
  riverView: "map",
  riverQuery: "",
  riverLoading: false,
  coalAssets: [],
  coalSummary: null,
  coalAnalysis: null,
  coalResearch: null,
  coalAnalysisView: "overview",
  coalDashboardTab: "overview",
  coalView: "analytics",
  dataHubSummary: null,
  dataHubPreview: null,
  dataHubProvider: null,
  gttTab: "overview",
  gttAnalytics: null,
  gttAnalyticsDatasetId: null,
  gttAnalyticsKey: "",
  gttDimensions: null,
  gttLeafletMap: null,
  gttTradeLayer: null,
  gttChartModes: { trend: "line", partners: "bars", reporters: "bars", commodities: "bars" },
  nppLoaded: false,
  nppRefreshTimer: null,
  continentLabels: null,
  countryLabels: null,
  renderedPortCount: 0,
  filters: {
    energy: { country: "", status: "operating" },
    commodities: { country: "", status: "operating" }
  }
};
let routeRecalculationTimer = null;

function workspaceInput(mode, id) {
  return document.querySelector(
    `details[data-mode="${mode}"] input[value="${id}"]`
  );
}

document.addEventListener("DOMContentLoaded", init);

async function init() {
  state.map = L.map("map", {
    preferCanvas: true,
    worldCopyJump: true,
    zoomControl: true,
    minZoom: 2
  }).setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM);
  setMapSkin("light");
  addEnglishMapLabels();
  state.portLayer = L.layerGroup().addTo(state.map);
  state.coalLayer = L.layerGroup().addTo(state.map);
  state.aisLayer = L.layerGroup().addTo(state.map);
  state.aisTrailLayer = L.layerGroup().addTo(state.map);
  state.routeLayer = L.layerGroup().addTo(state.map);
  state.weatherLayer = L.layerGroup();
  state.weatherSymbolLayer = L.layerGroup();
  state.riverLayer = L.layerGroup();
  state.map.on("zoomend", () => {
    renderPorts();
    if (state.coastalWeatherEnabled) renderCoastalWeather();
    if (state.mode === "rivers") renderRiverLevels();
  });
  loadAisPreferences();
  bindControls();
  updateCoastalWeatherDownload();
  await Promise.all([
    loadPortFacets(),
    loadWorkspaceFacets(),
    loadCoalWorkspace(),
    loadDataHubSummary()
  ]);
  await loadPorts();
  activateMode("ports");
}

function bindControls() {
  const syncCollapsedSection = section => {
    Array.from(section.children).forEach(child => {
      if (child.tagName === "SUMMARY") return;
      child.inert = !section.open;
      child.toggleAttribute("aria-hidden", !section.open);
      child.querySelectorAll("a, button, input, select, textarea, [tabindex]").forEach(control => {
        if (!section.open) {
          if (!control.hasAttribute("data-open-tabindex")) {
            control.setAttribute("data-open-tabindex", control.getAttribute("tabindex") || "");
          }
          control.setAttribute("tabindex", "-1");
        } else {
          const previous = control.getAttribute("data-open-tabindex");
          if (previous === "") control.removeAttribute("tabindex");
          else if (previous !== null) control.setAttribute("tabindex", previous);
          control.removeAttribute("data-open-tabindex");
        }
      });
    });
  };
  document.querySelectorAll("details.filter-section").forEach(section => {
    syncCollapsedSection(section);
    section.addEventListener("toggle", () => syncCollapsedSection(section));
  });
  document.querySelectorAll(".filter-section[data-mode]").forEach(section => {
    section.addEventListener("toggle", () => {
      if (section.open) activateMode(section.dataset.mode);
    });
  });
  document.querySelector(".voyage-section").addEventListener("toggle", event => {
    const section = event.currentTarget;
    if (section.open) {
      document.querySelectorAll(".filter-section[data-mode]").forEach(item => {
        item.open = false;
      });
      state.routeMode = true;
      state.routePickIndex = 0;
      if (!state.map.hasLayer(state.routeLayer)) state.routeLayer.addTo(state.map);
      closePortCard();
      renderPorts();
      updateRouteSelection();
      document.getElementById("route-pick").classList.add("active");
      document.getElementById("route-result").textContent =
        "Click a port dot for the origin, then another for the destination.";
    } else {
      state.routeMode = false;
      state.routePickIndex = 0;
      const button = document.getElementById("route-pick");
      button.classList.remove("active");
      button.textContent = "Select two ports on map";
      if (state.mode !== "ports" && state.map.hasLayer(state.routeLayer)) {
        state.map.removeLayer(state.routeLayer);
      }
      renderPorts();
    }
  });
  document.querySelectorAll("#energy-layers input, #renewable-layers input, #nuclear-layers input, #coal-layers input, #iron-layers input, #cement-layers input")
    .forEach(input => input.addEventListener("change", () => toggleAssetLayer(input)));
  document.getElementById("show-ports").addEventListener("change", renderPorts);
  document.getElementById("energy-show-ports").addEventListener("change", renderPorts);
  document.getElementById("commodity-show-ports").addEventListener("change", renderPorts);
  document.getElementById("ais-enabled").addEventListener("change", event => {
    setAisEnabled(event.target.checked);
  });
  document.getElementById("ais-refresh").addEventListener("click", () => refreshAisLayer());
  document.getElementById("ais-clear").addEventListener("click", clearAisVessels);
  document.getElementById("ais-display-mode").addEventListener("change", event => {
    state.aisDisplayMode = event.target.value === "selected" ? "selected" : "all";
    saveAisPreferences();
    renderAisVessels();
    if (state.aisEnabled) refreshAisLayer();
  });
  document.getElementById("ais-type-filter").addEventListener("change", event => {
    const allowed = new Set(["cargo_tanker", "cargo", "tanker", "all"]);
    state.aisTypeFilter = allowed.has(event.target.value)
      ? event.target.value
      : "cargo_tanker";
    saveAisPreferences();
    renderAisVessels();
  });
  document.querySelectorAll("#ais-region-options input").forEach(input => {
    input.addEventListener("change", () => {
      if (input.value === "world" && input.checked) {
        document.querySelectorAll("#ais-region-options input").forEach(option => {
          option.checked = option === input;
        });
      } else if (input.checked) {
        document.querySelector('#ais-region-options input[value="world"]').checked = false;
      }
      const checked = Array.from(
        document.querySelectorAll("#ais-region-options input:checked")
      );
      if (!checked.length) {
        const current = document.querySelector(
          '#ais-region-options input[value="current"]'
        );
        current.checked = true;
        checked.push(current);
      }
      state.aisRegions = new Set(checked.map(option => option.value));
      saveAisPreferences();
      updateAisRegionSummary();
      renderAisVessels();
      if (state.aisEnabled) refreshAisLayer();
    });
  });
  document.getElementById("ais-search-button").addEventListener("click", () => refreshAisLayer(true));
  document.getElementById("ais-search").addEventListener("keydown", event => {
    if (event.key === "Enter") refreshAisLayer(true);
  });
  document.getElementById("coastal-weather-enabled").addEventListener("change", event => {
    setCoastalWeatherEnabled(event.target.checked);
  });
  document.getElementById("coastal-weather-source").addEventListener("change", event => {
    state.coastalWeatherSource = event.target.value;
    updateCoastalWeatherDownload();
    if (state.coastalWeatherEnabled) {
      focusCoastalWeatherSource();
      loadCoastalWeather();
    }
  });
  document.getElementById("coastal-weather-day").addEventListener("change", event => {
    state.coastalWeatherHours = Number(event.target.value) || 0;
    if (state.coastalWeatherEnabled) loadCoastalWeather();
  });
  document.querySelectorAll("[data-weather-view]").forEach(button => {
    button.addEventListener("click", () => {
      if (state.mode !== "weather") activateMode("weather");
      setCoastalWeatherView(button.dataset.weatherView);
    });
  });
  document.getElementById("coastal-weather-location-type").addEventListener("change", event => {
    state.coastalWeatherLocationType = event.target.value;
    renderCoastalWeather();
    renderWeatherWorkspace();
  });
  document.getElementById("coastal-weather-data-class").addEventListener("change", event => {
    state.coastalWeatherDataClass = event.target.value;
    renderCoastalWeather();
    renderWeatherWorkspace();
  });
  document.getElementById("coastal-weather-port-status").addEventListener("change", event => {
    state.coastalWeatherPortStatus = event.target.value;
    renderCoastalWeather();
    renderWeatherWorkspace();
  });
  document.getElementById("weather-workspace-search").addEventListener("input", event => {
    state.coastalWeatherQuery = event.target.value.trim().toLowerCase();
    renderWeatherWorkspace();
  });
  document.querySelectorAll(".weather-parameters input").forEach(input => {
    input.addEventListener("change", () => {
      state.coastalWeatherParameters = new Set(
        Array.from(document.querySelectorAll(".weather-parameters input:checked"))
          .map(item => item.value)
      );
      renderCoastalWeather();
    });
  });
  document.getElementById("coastal-weather-animation").addEventListener("change", event => {
    state.coastalWeatherAnimated = event.target.checked;
    renderCoastalWeather();
  });
  document.getElementById("coastal-weather-polygons").addEventListener("change", event => {
    state.coastalWeatherPolygonsVisible = event.target.checked;
    renderCoastalWeather();
  });
  document.getElementById("coastal-weather-refresh").addEventListener("click", () => {
    loadCoastalWeather(true);
  });
  document.querySelectorAll("[data-river-view]").forEach(button => {
    button.addEventListener("click", () => {
      if (state.mode !== "rivers") activateMode("rivers");
      setRiverView(button.dataset.riverView);
    });
  });
  ["river-waterway-filter", "river-country-filter", "river-type-filter", "river-status-filter"].forEach(id => {
    document.getElementById(id).addEventListener("change", () => {
      renderRiverLevels();
      renderRiverWorkspace();
      updateRiverExportLink();
    });
  });
  document.getElementById("river-workspace-search").addEventListener("input", event => {
    state.riverQuery = event.target.value.trim().toLowerCase();
    renderRiverWorkspace();
  });
  document.getElementById("river-level-refresh").addEventListener("click", () => loadRiverLevels(true));
  document.querySelectorAll("#coal-workspace-layers input, #coal-consumer-layers input").forEach(input => {
    input.addEventListener("change", renderCoalLayers);
  });
  document.getElementById("coal-asset-status").addEventListener("change", loadCoalWorkspace);
  document.getElementById("iron-terminal-role").addEventListener("change", () => {
    const input = workspaceInput("commodities", "iron_ore_terminals");
    if (input?.checked) applyWorkspaceFilters("commodities");
  });
  document.querySelectorAll("[data-coal-view]").forEach(button => {
    button.addEventListener("click", () => {
      if (state.mode !== "coal") activateMode("coal");
      setCoalView(button.dataset.coalView);
    });
  });
  document.getElementById("coal-analysis-apply").addEventListener("click", loadCoalDashboard);
  document.getElementById("coal-analysis-frequency").addEventListener("change", loadCoalDashboard);
  document.getElementById("coal-analysis-focus").addEventListener("change", loadCoalDashboard);
  document.getElementById("coal-analysis-comparison").addEventListener("change", loadCoalDashboard);
  document.querySelectorAll("[data-coal-range]").forEach(button => {
    button.addEventListener("click", () => applyCoalRangePreset(button.dataset.coalRange));
  });
  document.querySelectorAll("[data-coal-dashboard-tab]").forEach(button => {
    button.addEventListener("click", () => setCoalDashboardTab(button.dataset.coalDashboardTab));
  });
  document.getElementById("coal-upload").addEventListener("click", () => {
    document.getElementById("coal-upload-input").click();
  });
  document.getElementById("coal-upload-input").addEventListener("change", uploadCoalDataset);
  document.getElementById("coal-export").addEventListener("click", exportCoalData);
  document.getElementById("coal-research-run").addEventListener("click", runCoalResearch);
  document.getElementById("coal-research-question").addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runCoalResearch();
  });
  document.querySelectorAll(".coal-research-prompts button").forEach(button => {
    button.addEventListener("click", () => {
      document.getElementById("coal-research-question").value = button.textContent.trim();
      runCoalResearch();
    });
  });
  document.getElementById("coal-metric").addEventListener("change", refreshCoalActionState);
  document.getElementById("coal-run-analysis").addEventListener("click", () => {
    const dataset = document.getElementById("coal-metric").selectedOptions[0].textContent;
    const frequency = document.getElementById("coal-frequency").selectedOptions[0].textContent;
    const coalType = document.getElementById("coal-grade").selectedOptions[0].textContent;
    const period = document.getElementById("coal-period").selectedOptions[0].textContent;
    document.getElementById("coal-research-question").value =
      `Show ${frequency.toLowerCase()} ${coalType.toLowerCase()} ${dataset.toLowerCase()} for ${period.toLowerCase()}.`;
    runCoalResearch();
  });
  document.getElementById("npp-refresh").addEventListener("click", () => loadNppPower(true));
  document.getElementById("gtt-open-workspace").addEventListener("click", () => activateMode("gtt"));
  document.getElementById("gtt-back-main").addEventListener("click", () => activateMode("ports"));
  document.querySelectorAll("[data-gtt-tab]").forEach(button => {
    button.addEventListener("click", () => setGttTab(button.dataset.gttTab));
  });
  document.querySelectorAll("[data-gtt-chart-mode]").forEach(select => select.addEventListener("change", () => {
    state.gttChartModes[select.dataset.gttChartMode] = select.value;
    renderGttOverview(filteredGttDatasets());
  }));
  ["gtt-flow-filter", "gtt-year-from", "gtt-year-to", "gtt-frequency-filter", "gtt-metric-filter", "gtt-unit-filter"].forEach(id => {
    document.getElementById(id).addEventListener("change", renderGttWorkspace);
  });
  ["gtt-exporter-filter", "gtt-importer-filter", "gtt-hs-filter"].forEach(id => {
    document.getElementById(id).addEventListener("change", () => { state.gttAnalyticsKey = ""; renderGttWorkspace(); });
  });
  ["gtt-map-side", "gtt-map-view"].forEach(id => document.getElementById(id).addEventListener("change", () => renderGttTradeMap(state.gttAnalytics)));
  document.getElementById("gtt-reset-filters").addEventListener("click", resetGttFilters);
  document.getElementById("gtt-run-compare").addEventListener("click", compareGttDatasets);
  ["gtt-upload-file", "gtt-upload-file-secondary"].forEach(id => document.getElementById(id).addEventListener("click", () => openDataHubUpload("gtt")));
  document.getElementById("gtt-connect-api").addEventListener("click", () => openDataHubApi("gtt"));
  document.getElementById("datahub-open-workspace").addEventListener("click", () => { activateMode("datahub"); setDataHubTab("visualize"); });
  document.getElementById("datahub-provider-filter").addEventListener("change", renderDataHubCatalog);
  document.querySelectorAll("[data-datahub-tab]").forEach(button => {
    button.addEventListener("click", () => setDataHubTab(button.dataset.datahubTab));
  });
  document.getElementById("datahub-choose-file").addEventListener("click", () => document.getElementById("datahub-file-input").click());
  document.getElementById("datahub-file-input").addEventListener("change", event => {
    document.getElementById("datahub-selected-file").textContent = event.target.files[0]?.name || "No file selected";
  });
  document.getElementById("datahub-submit-upload").addEventListener("click", uploadDataHubDataset);
  document.getElementById("datahub-submit-api").addEventListener("click", saveDataHubApiConnection);
  document.getElementById("datahub-compare").addEventListener("click", compareDataHubDatasets);
  document.getElementById("datahub-propose").addEventListener("click", proposeDataHubRelationship);
  document.getElementById("datahub-viz-dataset").addEventListener("change", loadDataHubPreview);
  document.getElementById("datahub-render-chart").addEventListener("click", renderDataHubVisualization);
  document.getElementById("port-country").addEventListener("change", loadPorts);
  document.getElementById("port-size").addEventListener("change", loadPorts);
  document.querySelectorAll("#port-categories input").forEach(input => input.addEventListener("change", loadPorts));
  document.getElementById("energy-apply").addEventListener("click", () => applyWorkspaceFilters("energy"));
  document.getElementById("commodity-apply").addEventListener("click", () => applyWorkspaceFilters("commodities"));
  document.getElementById("coal-terminal-role").addEventListener("change", () => applyWorkspaceFilters("commodities"));
  document.getElementById("route-pick").addEventListener("click", startRoutePicking);
  document.getElementById("route-reset").addEventListener("click", resetRoute);
  [
    ["route-from-input", 0],
    ["route-to-input", 1]
  ].forEach(([id, index]) => {
    const input = document.getElementById(id);
    input.addEventListener("input", () => input.setCustomValidity(""));
    input.addEventListener("change", () => selectRoutePortFromInput(index, input));
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        selectRoutePortFromInput(index, input);
      }
    });
  });
  document.querySelectorAll(
    "#route-speed, #route-sea-margin, #route-port-hours, #route-canal-hours, .route-restrictions input"
  ).forEach(input => {
    const schedule = () => {
      if (!state.routePorts[0] || !state.routePorts[1]) return;
      window.clearTimeout(routeRecalculationTimer);
      routeRecalculationTimer = window.setTimeout(calculateRoute, 300);
    };
    input.addEventListener("change", schedule);
    if (input.type === "number") input.addEventListener("input", schedule);
  });
  document.getElementById("close-port-card").addEventListener("click", closePortCard);
  document.getElementById("fit-world").addEventListener("click", () => state.map.setView([18, 10], 2));
  document.getElementById("map-skin").addEventListener("change", event => {
    setMapSkin(event.target.value);
  });
}

function activateMode(mode) {
  state.mode = mode;
  closePortCard();
  const voyageSection = document.querySelector(".voyage-section");
  if (voyageSection.open) voyageSection.open = false;
  state.routeMode = false;
  state.routePickIndex = 0;
  document.querySelectorAll(".filter-section[data-mode]").forEach(section => {
    if (section.dataset.mode !== mode) section.open = false;
  });
  state.assetLayers.forEach((layer, id) => {
    if (state.map.hasLayer(layer)) state.map.removeLayer(layer);
  });
  const coalOnly = mode === "coal";
  const dataHubOnly = mode === "datahub";
  const gttOnly = mode === "gtt";
  const riverOnly = mode === "rivers";
  if (!riverOnly && state.riverLayer && state.map.hasLayer(state.riverLayer)) {
    state.map.removeLayer(state.riverLayer);
  }
  document.querySelector(".river-key-item").hidden = !riverOnly;
  [state.aisLayer, state.aisTrailLayer, state.routeLayer].forEach(layer => {
    if (layer && state.map.hasLayer(layer)) state.map.removeLayer(layer);
  });
  if (!coalOnly && !dataHubOnly && !gttOnly && state.aisEnabled) {
    state.aisLayer.addTo(state.map);
    state.aisTrailLayer.addTo(state.map);
    renderAisVessels();
  }
  if (mode === "ports") state.routeLayer.addTo(state.map);
  if (mode === "energy" || mode === "commodities") {
    WORKSPACE_LAYERS[mode].forEach(id => {
      const input = workspaceInput(mode, id);
      if (input?.checked) toggleAssetLayer(input);
    });
  }
  const coalHeader = document.getElementById("coal-workspace-header");
  coalHeader.hidden = mode !== "coal";
  document.getElementById("weather-data-surface").hidden = true;
  document.getElementById("river-data-surface").hidden = true;
  document.getElementById("datahub-surface").hidden = !dataHubOnly;
  document.getElementById("gtt-surface").hidden = !gttOnly;
  if (mode === "coal") {
    document.getElementById("datahub-surface").hidden = true;
    setCoalView(state.coalView);
    renderCoalLayers();
    state.map.fitBounds([[6, 68], [37, 98]], { padding: [25, 25] });
  } else if (dataHubOnly || gttOnly) {
    state.coalLayer.clearLayers();
    document.getElementById("coal-data-surface").hidden = true;
    document.getElementById("npp-power-surface").hidden = true;
    document.getElementById("map").hidden = true;
    document.querySelector(".map-topbar").hidden = true;
    document.querySelector(".map-key").hidden = true;
    loadDataHubSummary();
    if (gttOnly) setGttTab(state.gttTab);
  } else {
    state.coalLayer.clearLayers();
    document.getElementById("datahub-surface").hidden = true;
    document.getElementById("gtt-surface").hidden = true;
    document.getElementById("coal-data-surface").hidden = true;
    document.getElementById("npp-power-surface").hidden = true;
    document.getElementById("map").hidden = false;
    document.querySelector(".map-topbar").hidden = false;
    document.querySelector(".map-key").hidden = false;
    if (mode === "weather") setCoastalWeatherView(state.coastalWeatherView);
    if (riverOnly) {
      if (!state.map.hasLayer(state.riverLayer)) state.riverLayer.addTo(state.map);
      setRiverView(state.riverView);
      loadRiverLevels();
      if (!state.riverRows.length) state.map.fitBounds([[-12, -100], [56, 18]], { padding: [20, 20] });
    } else if (state.map.hasLayer(state.riverLayer)) {
      state.map.removeLayer(state.riverLayer);
    }
    setTimeout(() => state.map.invalidateSize(), 0);
  }
  renderPorts();
  updateActiveCounts();
}

const DATA_HUB_PROVIDER_LABELS = {
  gtt: "GTT", kpler: "Kpler", oceanbolt: "Oceanbolt",
  axs_marine: "AXS Marine", custom: "Custom data", hrp_app: "HRP app data"
};

async function loadDataHubSummary() {
  try {
    const response = await fetch("/api/data-hub/summary");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Data Hub is unavailable");
    state.dataHubSummary = payload;
    renderDataHubSummary();
  } catch (error) {
    document.getElementById("datahub-sidebar-status").textContent = "Unavailable";
    const catalog = document.getElementById("datahub-catalog");
    if (catalog) catalog.innerHTML = `<div class="datahub-empty"><strong>Data Hub unavailable</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

function renderDataHubSummary() {
  const payload = state.dataHubSummary;
  if (!payload) return;
  const totals = payload.totals || {};
  const values = {
    "datahub-sidebar-datasets": totals.datasets || 0,
    "datahub-sidebar-rows": Number(totals.rows || 0).toLocaleString(),
    "datahub-sidebar-due": totals.overdue || 0,
    "datahub-kpi-datasets": totals.datasets || 0,
    "datahub-kpi-rows": Number(totals.rows || 0).toLocaleString(),
    "datahub-kpi-overdue": totals.overdue || 0,
    "datahub-kpi-relations": totals.approved_relationships || 0
  };
  Object.entries(values).forEach(([id, value]) => { document.getElementById(id).textContent = value; });
  document.getElementById("datahub-sidebar-status").textContent = totals.overdue ? `${totals.overdue} update${totals.overdue === 1 ? "" : "s"} due` : "Master store";
  document.getElementById("datahub-master-file").textContent = payload.master_file || "provider_master.sqlite3";
  document.getElementById("datahub-provider-grid").innerHTML = (payload.providers || []).map(provider => {
    const latest = provider.latest;
    const freshness = provider.freshness || { status: "missing", label: "No data uploaded" };
    return `<article class="datahub-provider-card ${escapeAttr(freshness.status)}" style="--provider-accent:${escapeAttr(provider.accent)}">
      <header><div><span>${escapeHtml(provider.label)}</span><strong>${provider.dataset_count} dataset${provider.dataset_count === 1 ? "" : "s"}</strong></div><i></i></header>
      <div class="datahub-provider-latest">
        <small>LATEST DATA</small>
        <b>${latest ? escapeHtml(latest.dataset_name) : "Awaiting first upload"}</b>
        <span>${latest ? `${Number(latest.row_count).toLocaleString()} rows · ${formatDataHubDate(latest.data_end || latest.uploaded_at)}` : "Excel, CSV, JSON or PDF"}</span>
      </div>
      <div class="datahub-freshness"><i></i><span>${escapeHtml(freshness.label)}</span></div>
      <footer><button type="button" data-provider-upload="${escapeAttr(provider.id)}">Upload data</button><button type="button" data-provider-api="${escapeAttr(provider.id)}">${provider.connection ? `API ${escapeHtml(provider.connection.key_mask)}` : "Connect API"}</button></footer>
    </article>`;
  }).join("");
  document.querySelectorAll("[data-provider-upload]").forEach(button => button.addEventListener("click", () => openDataHubUpload(button.dataset.providerUpload)));
  document.querySelectorAll("[data-provider-api]").forEach(button => button.addEventListener("click", () => openDataHubApi(button.dataset.providerApi)));
  populateDataHubDatasetSelectors();
  renderDataHubCatalog();
  renderGttWorkspace();
}

function setGttTab(tab) {
  state.gttTab = tab;
  document.querySelectorAll("[data-gtt-tab]").forEach(button => button.classList.toggle("active", button.dataset.gttTab === tab));
  document.querySelectorAll("[data-gtt-panel]").forEach(panel => { panel.hidden = panel.dataset.gttPanel !== tab; });
  renderGttWorkspace();
}

function resetGttFilters() {
  ["gtt-flow-filter", "gtt-exporter-filter", "gtt-importer-filter", "gtt-hs-filter", "gtt-year-from", "gtt-year-to", "gtt-frequency-filter"].forEach(id => { document.getElementById(id).value = ""; });
  document.getElementById("gtt-metric-filter").value = "quantity";
  document.getElementById("gtt-unit-filter").value = "mt";
  state.gttAnalyticsKey = "";
  renderGttWorkspace();
}

function gttDatasetYear(value) {
  if (!value) return null;
  const match = String(value).match(/(?:19|20)\d{2}/);
  return match ? Number(match[0]) : null;
}

function filteredGttDatasets() {
  const all = (state.dataHubSummary?.datasets || []).filter(item => item.provider === "gtt");
  const frequency = document.getElementById("gtt-frequency-filter")?.value || "";
  const fromYear = Number(document.getElementById("gtt-year-from")?.value || 0);
  const toYear = Number(document.getElementById("gtt-year-to")?.value || 9999);
  return all.filter(item => {
    const start = gttDatasetYear(item.data_start) || -Infinity;
    const end = gttDatasetYear(item.data_end) || Infinity;
    return (!frequency || item.frequency === frequency) && end >= fromYear && start <= toYear;
  });
}

function populateGttYearFilters(datasets) {
  const years = new Set();
  datasets.forEach(item => {
    const start = gttDatasetYear(item.data_start); const end = gttDatasetYear(item.data_end);
    if (start && end && end >= start && end - start <= 100) {
      for (let year = start; year <= end; year += 1) years.add(year);
    } else {
      if (start) years.add(start); if (end) years.add(end);
    }
  });
  const ordered = Array.from(years).sort((a, b) => a - b);
  [["gtt-year-from", "Earliest available"], ["gtt-year-to", "Latest available"]].forEach(([id, label]) => {
    const select = document.getElementById(id); const current = select.value;
    select.innerHTML = `<option value="">${label}</option>${ordered.map(year => `<option value="${year}">${year}</option>`).join("")}`;
    if (ordered.includes(Number(current))) select.value = current;
  });
}

function gttCoverageLabel(datasets) {
  const starts = datasets.map(item => item.data_start).filter(Boolean).sort();
  const ends = datasets.map(item => item.data_end).filter(Boolean).sort();
  if (!starts.length || !ends.length) return "Coverage not detected";
  return `${formatDataHubDate(starts[0])} – ${formatDataHubDate(ends.at(-1))}`;
}

function renderGttWorkspace() {
  if (!state.dataHubSummary) return;
  const allGtt = (state.dataHubSummary.datasets || []).filter(item => item.provider === "gtt");
  populateGttYearFilters(allGtt);
  const datasets = filteredGttDatasets();
  const rows = datasets.reduce((sum, item) => sum + Number(item.row_count || 0), 0);
  const latest = datasets.map(item => item.data_end).filter(Boolean).sort().at(-1);
  const reviewCount = datasets.filter(item => item.quality_status !== "profiled").length;
  const overdue = datasets.filter(item => item.freshness?.status === "overdue").length;
  const coverage = gttCoverageLabel(datasets);
  const status = !allGtt.length ? "Awaiting data" : overdue ? `${overdue} update${overdue === 1 ? "" : "s"} due` : "Source ready";
  const textValues = {
    "gtt-sidebar-status": status,
    "gtt-sidebar-datasets": allGtt.length,
    "gtt-sidebar-rows": allGtt.reduce((sum, item) => sum + Number(item.row_count || 0), 0).toLocaleString(),
    "gtt-header-status": !allGtt.length ? "Awaiting validated GTT data" : reviewCount ? `${reviewCount} dataset${reviewCount === 1 ? "" : "s"} require review` : "Profiled GTT sources available",
    "gtt-header-coverage": allGtt.length ? gttCoverageLabel(allGtt) : "No reporting coverage",
    "gtt-kpi-datasets": datasets.length || "—",
    "gtt-kpi-rows": rows ? rows.toLocaleString() : "—",
    "gtt-kpi-coverage": datasets.length ? `${gttDatasetYear(datasets.map(item => item.data_start).filter(Boolean).sort()[0]) || "—"}–${gttDatasetYear(latest) || "—"}` : "—",
    "gtt-kpi-latest": latest ? formatDataHubDate(latest) : "—",
    "gtt-kpi-quality": !datasets.length ? "—" : reviewCount ? "Review needed" : "Profiled"
  };
  Object.entries(textValues).forEach(([id, value]) => { const element = document.getElementById(id); if (element) element.textContent = value; });
  const analyticsDataset = [...datasets].sort((a, b) => String(b.data_end || b.uploaded_at || "").localeCompare(String(a.data_end || a.uploaded_at || "")))[0];
  const analyticsKey = analyticsDataset ? `${analyticsDataset.id}|${document.getElementById("gtt-exporter-filter")?.value || ""}|${document.getElementById("gtt-importer-filter")?.value || ""}|${document.getElementById("gtt-hs-filter")?.value || ""}|${document.getElementById("gtt-year-from")?.value || ""}|${document.getElementById("gtt-year-to")?.value || ""}` : "";
  if (analyticsDataset && state.gttAnalyticsKey !== analyticsKey) loadGttAnalytics(analyticsDataset.id, analyticsKey);
  renderGttOverview(datasets);
  renderGttCatalog("gtt-explore-catalog", datasets);
  renderGttCatalog("gtt-upload-catalog", allGtt);
  populateGttCompare(datasets);
  renderGttGatedViews(allGtt);
  renderGttAdmin(allGtt);
}

function populateGttDimensionFilters(payload) {
  if (!state.gttDimensions || (!payload?.filters?.reporter && !payload?.filters?.partner && !payload?.filters?.hs_code)) {
    state.gttDimensions = payload?.dimensions || {};
  }
  const dimensions = state.gttDimensions || {};
  [["gtt-exporter-filter", "All exporters", dimensions.reporters], ["gtt-importer-filter", "All importers", dimensions.partners], ["gtt-hs-filter", "All HS codes", dimensions.hs_codes]].forEach(([id, placeholder, values]) => {
    const select = document.getElementById(id); if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${placeholder}</option>${(values || []).map(value => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`).join("")}`;
    if ((values || []).includes(current)) select.value = current;
  });
}

async function loadGttAnalytics(datasetId, analyticsKey = datasetId) {
  state.gttAnalyticsDatasetId = datasetId;
  state.gttAnalyticsKey = analyticsKey;
  state.gttAnalytics = null;
  renderGttOverview(filteredGttDatasets());
  try {
    const params = new URLSearchParams();
    const exporter = document.getElementById("gtt-exporter-filter")?.value; const importer = document.getElementById("gtt-importer-filter")?.value; const hs = document.getElementById("gtt-hs-filter")?.value;
    const from = document.getElementById("gtt-year-from")?.value; const to = document.getElementById("gtt-year-to")?.value;
    if (exporter) params.set("reporter", exporter); if (importer) params.set("partner", importer); if (hs) params.set("hs_code", hs); if (from) params.set("year_from", from); if (to) params.set("year_to", to);
    const response = await fetch(`/api/data-hub/datasets/${encodeURIComponent(datasetId)}/analytics${params.toString() ? `?${params}` : ""}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Trade analytics are unavailable");
    if (state.gttAnalyticsKey !== analyticsKey) return;
    state.gttAnalytics = payload;
    populateGttDimensionFilters(payload);
    renderGttOverview(filteredGttDatasets());
  } catch (error) {
    if (state.gttAnalyticsKey !== analyticsKey) return;
    state.gttAnalytics = { error: error.message };
    renderGttOverview(filteredGttDatasets());
  }
}

function compactTradeNumber(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}

function gttRankRows(rows) {
  if (!rows?.length) return `<div class="gtt-empty"><strong>No ranked dimension</strong><span>This field was not available in the source.</span></div>`;
  const max = Math.max(...rows.map(row => Number(row.value || 0)), 1);
  return rows.slice(0, 7).map((row, index) => `<div class="gtt-rank-row"><b>${index + 1}</b><span title="${escapeAttr(row.label)}">${escapeHtml(row.label)}</span><i style="--bar:${Math.max(2, Number(row.value || 0) / max * 100)}%"></i><strong title="${Number(row.value || 0).toLocaleString()} MT">${compactTradeNumber(row.value)} MT</strong></div>`).join("");
}

function gttRankTable(rows) {
  if (!rows?.length) return `<div class="gtt-empty"><strong>No ranked dimension</strong><span>This field was not available in the source.</span></div>`;
  return `<table class="gtt-mini-table"><thead><tr><th>Rank</th><th>Entity</th><th>Value</th></tr></thead><tbody>${rows.slice(0, 8).map((row, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(row.label)}</td><td>${compactTradeNumber(row.value)} MT</td></tr>`).join("")}</tbody></table>`;
}

function gttTrendSvg(rows, metricKey = "quantity_mt", unitLabel = "MT", mode = "line") {
  const width = 860, height = 285, left = 64, right = 18, top = 18, bottom = 40;
  if (!rows.length) return `<div class="gtt-empty"><strong>No trend for selected period</strong><span>Adjust the year filters to include source coverage.</span></div>`;
  const values = rows.map(row => Number(row[metricKey] || 0));
  const maxValue = Math.max(...values, 1);
  const innerWidth = width - left - right, innerHeight = height - top - bottom;
  const points = rows.map((row, index) => {
    const x = left + (rows.length === 1 ? innerWidth / 2 : index / (rows.length - 1) * innerWidth);
    const y = top + innerHeight - Number(row[metricKey] || 0) / maxValue * innerHeight;
    return { x, y, row };
  });
  const line = mode === "step"
    ? points.map((point, index) => index ? `H${point.x.toFixed(1)} V${point.y.toFixed(1)}` : `M${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")
    : points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${line} L${points.at(-1).x.toFixed(1)},${(top + innerHeight).toFixed(1)} L${points[0].x.toFixed(1)},${(top + innerHeight).toFixed(1)} Z`;
  const grid = Array.from({ length: 5 }, (_, index) => {
    const fraction = index / 4, y = top + innerHeight - fraction * innerHeight;
    return `<line class="grid" x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/><text class="axis" x="${left-8}" y="${y+3}" text-anchor="end">${compactTradeNumber(maxValue * fraction)}</text>`;
  }).join("");
  const tickIndexes = Array.from(new Set(Array.from({ length: Math.min(7, rows.length) }, (_, index) => Math.round(index * (rows.length - 1) / Math.max(1, Math.min(7, rows.length) - 1)))));
  const ticks = tickIndexes.map(index => `<text class="axis" x="${points[index].x}" y="${height-14}" text-anchor="middle">${escapeHtml(formatMonthYear(rows[index].period))}</text>`).join("");
  const dots = points.map(point => `<circle class="point" cx="${point.x}" cy="${point.y}" r="3"><title>${escapeHtml(formatMonthYear(point.row.period))}: ${Number(point.row[metricKey] || 0).toLocaleString()} ${unitLabel}</title></circle>`).join("");
  const areaMarkup = mode === "area" ? `<path class="area" d="${area}"/>` : "";
  const dotsMarkup = mode === "scatter" ? dots : (mode === "line" || mode === "step" ? dots : "");
  return `<svg class="gtt-line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Reported ${escapeAttr(unitLabel)} trend"><defs><linearGradient id="gttArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3f83d7"/><stop offset="1" stop-color="#dfeafa"/></linearGradient></defs>${grid}${areaMarkup}<path class="line" d="${line}"/>${dotsMarkup}${ticks}</svg>`;
}

function gttRankVisual(rows, mode) {
  if (!rows?.length) return gttRankRows(rows);
  if (mode === "table") return gttRankTable(rows);
  if (mode === "bars") return gttRankRows(rows);
  const series = rows.slice(0, 8).map(row => ({ period: row.label, quantity_mt: Number(row.value || 0) }));
  if (["line", "area", "scatter", "step"].includes(mode)) return gttTrendSvg(series, "quantity_mt", "MT", mode);
  if (mode === "bar") return gttBarSvg(series, "quantity_mt", "MT");
  return `<div class="gtt-empty"><strong>${escapeHtml(labelize(mode))} is not ideal for a categorical ranking</strong><span>Showing the ranked entities as bars or a table keeps country and commodity comparisons readable.</span></div>`;
}

const GTT_COUNTRY_COORDS = {
  IN: [22.6, 79.4], CN: [35.8, 103.8], JP: [36.2, 138.3], KR: [36.4, 127.9], US: [39.8, -98.6], CA: [56.1, -106.3], BR: [-10.8, -52.9], AU: [-25.3, 133.8], ID: [-2.2, 117.3], SG: [1.35, 103.8], VN: [14.1, 108.3], TH: [15.6, 101], MY: [4.2, 102], RU: [61.5, 105.3], DE: [51.2, 10.5], GB: [54.2, -2.7], NL: [52.2, 5.3], FR: [46.3, 2.2], ES: [40.2, -3.7], IT: [41.9, 12.6], ZA: [-30.6, 22.9], AE: [23.4, 53.8], SA: [23.9, 45.1], QA: [25.3, 51.2], TR: [39, 35.2], CL: [-35.7, -71.5], AR: [-38.4, -63.6], MX: [23.6, -102.6], EG: [26.8, 30.8], NG: [9.1, 8.7], PL: [51.9, 19.1], BE: [50.5, 4.5], SE: [60.1, 18.6], NO: [61.2, 8.5], DK: [56.2, 9.5], FI: [64.9, 26]
};

function gttCountryPoint(iso, index = 0) {
  const known = GTT_COUNTRY_COORDS[String(iso || "").toUpperCase()];
  if (known) return known;
  // Keep a record with an unknown ISO code visible rather than dropping it.
  return [Math.max(-50, Math.min(65, -30 + (index * 17) % 95)), -150 + (index * 47) % 285];
}

function ensureGttLeafletMap() {
  const container = document.getElementById("gtt-trade-map");
  if (!container || state.gttLeafletMap || typeof L === "undefined") return state.gttLeafletMap;
  container.innerHTML = "";
  const map = L.map(container, {
    zoomControl: false,
    attributionControl: true,
    worldCopyJump: true,
    minZoom: 1,
    maxZoom: 7,
    preferCanvas: true
  }).setView([20, 10], 2);
  // Use the same clean, neutral Esri canvas layer as the main product map.  It
  // keeps trade routes readable and avoids the variable cartography of public
  // street tiles.
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 7, attribution: "Tiles © Esri" }
  ).addTo(map);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 7, pane: "overlayPane", attribution: "Labels © Esri" }
  ).addTo(map);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control.scale({ position: "bottomleft", imperial: false, maxWidth: 90 }).addTo(map);
  state.gttLeafletMap = map;
  state.gttTradeLayer = L.layerGroup().addTo(map);
  return map;
}

function renderGttTradeMap(analytics) {
  const container = document.getElementById("gtt-trade-map");
  const card = document.getElementById("gtt-trade-map-card");
  if (!container || document.getElementById("gtt-surface")?.hidden) return;
  const map = ensureGttLeafletMap();
  if (!map) return;
  map.invalidateSize();
  state.gttTradeLayer.clearLayers();
  const flows = analytics?.map_flows || [];
  if (!flows.length) {
    map.setView([20, 10], 2);
    if (card) card.hidden = true;
    return;
  }
  const side = document.getElementById("gtt-map-side")?.value || "exporter";
  const view = document.getElementById("gtt-map-view")?.value || "flows";
  const totals = new Map();
  flows.forEach((flow, index) => {
    const label = side === "exporter" ? flow.exporter : flow.importer;
    const iso = side === "exporter" ? flow.exporter_iso2 : flow.importer_iso2;
    const item = totals.get(label) || { label, iso, value: 0, flows: [], index };
    item.value += Number(flow.quantity_mt || 0); item.flows.push(flow); totals.set(label, item);
  });
  const countries = Array.from(totals.values()).sort((a, b) => b.value - a.value).slice(0, 36);
  const max = Math.max(...countries.map(item => item.value), 1);
  const colors = ["#0b5b9c", "#ef3d48", "#4f8fba", "#d8902f", "#6e5aa6", "#26805a", "#116a75", "#9d5579"];
  const points = new Map(countries.map(item => [item.label, gttCountryPoint(item.iso, item.index)]));
  if (view === "flows") {
    flows.slice(0, 100).forEach((flow, index) => {
      const start = gttCountryPoint(flow.exporter_iso2, index);
      const end = gttCountryPoint(flow.importer_iso2, index + 1);
      L.polyline([start, end], { color: "#80add0", weight: 1.2, opacity: .52, interactive: false }).addTo(state.gttTradeLayer);
    });
  }
  countries.forEach((item, index) => {
    const radius = 6 + Math.sqrt(item.value / max) * 16;
    const color = colors[index % colors.length];
    const marker = L.circleMarker(points.get(item.label), { radius, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }).addTo(state.gttTradeLayer);
    const show = () => {
      if (!card) return;
      card.hidden = false;
      card.innerHTML = `<strong>${escapeHtml(item.label)}</strong><span>${side === "exporter" ? "Exporter" : "Importer"} total · ${compactTradeNumber(item.value)} MT</span><small>${item.flows.slice(0, 5).map(flow => `${escapeHtml(flow.exporter)} → ${escapeHtml(flow.importer)} · ${compactTradeNumber(flow.quantity_mt)} MT`).join("<br>")}</small>`;
    };
    marker.bindTooltip(`<strong>${escapeHtml(item.label)}</strong><br>${compactTradeNumber(item.value)} MT`, { sticky: true, className: "weather-leaflet-tooltip" });
    marker.on({ mouseover: show, click: show, focus: show });
  });
  const bounds = countries.map(item => points.get(item.label));
  if (bounds.length > 1) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 3 });
  else map.setView(bounds[0], 3);
}

function renderGttCountryProfile(analytics) {
  const title = document.getElementById("gtt-country-name");
  const subtitle = document.getElementById("gtt-country-subtitle");
  const container = document.getElementById("gtt-country-profile-content");
  if (!title || !subtitle || !container) return;
  if (!analytics || analytics.error) {
    title.textContent = "Selected country";
    subtitle.textContent = "Choose an exporter or importer to analyse trade.";
    container.innerHTML = `<div class="gtt-profile-note">Country profile will populate from the validated bilateral trade rows.</div>`;
    return;
  }
  const filters = analytics.filters || {};
  const isExporter = Boolean(filters.reporter);
  const selected = filters.reporter || filters.partner || analytics.top_reporters?.[0]?.label || analytics.top_partners?.[0]?.label || "All countries";
  const total = Number(analytics.metrics?.quantity_mt || 0);
  const counterparty = isExporter ? analytics.top_partners?.[0] : analytics.top_reporters?.[0];
  title.textContent = selected;
  subtitle.textContent = `${isExporter ? "Exporter" : filters.partner ? "Importer" : "Top reporting market"} · selected trade analysis`;
  container.innerHTML = `<article><span>Total quantity</span><strong>${compactTradeNumber(total)} MT</strong><small>Selected time period and HS-code scope</small></article><article><span>${isExporter ? "Top destination" : "Top origin"}</span><strong>${escapeHtml(counterparty?.label || "—")}</strong><small>${compactTradeNumber(counterparty?.value)} MT</small></article><article><span>Trade partners</span><strong>${analytics.metrics?.partner_count ?? "—"}</strong><small>Distinct countries represented</small></article><article><span>Commodity / HS</span><strong>${escapeHtml(filters.hs_code || analytics.dimensions?.hs_codes?.[0] || "All")}</strong><small>${analytics.metrics?.commodity_count ?? "—"} commodity descriptions</small></article><div class="gtt-profile-note">Use the exporter and importer filters above to change the country profile, map and all charts together.</div>`;
}

function gttBarSvg(rows, metricKey, unitLabel) {
  const width = 860, height = 285, left = 64, right = 18, top = 18, bottom = 40;
  if (!rows.length) return `<div class="gtt-empty"><strong>No trend for selected period</strong><span>Adjust the year filters to include source coverage.</span></div>`;
  const maxValue = Math.max(...rows.map(row => Number(row[metricKey] || 0)), 1);
  const innerWidth = width - left - right, innerHeight = height - top - bottom;
  const barWidth = Math.max(3, Math.min(28, innerWidth / rows.length * .72));
  const y = value => top + innerHeight - Number(value || 0) / maxValue * innerHeight;
  const grid = Array.from({ length: 5 }, (_, index) => { const fraction = index / 4, gy = top + innerHeight - fraction * innerHeight; return `<line class="grid" x1="${left}" y1="${gy}" x2="${width-right}" y2="${gy}"/><text class="axis" x="${left-8}" y="${gy+3}" text-anchor="end">${compactTradeNumber(maxValue * fraction)}</text>`; }).join("");
  const bars = rows.map((row, index) => { const x = left + (index + .5) / rows.length * innerWidth, value = Number(row[metricKey] || 0); return `<rect class="point" x="${x - barWidth/2}" y="${y(value)}" width="${barWidth}" height="${top+innerHeight-y(value)}" fill="#0b5b9c"><title>${escapeHtml(formatMonthYear(row.period))}: ${value.toLocaleString()} ${unitLabel}</title></rect>`; }).join("");
  const labelIndexes = Array.from(new Set(Array.from({length: Math.min(7, rows.length)}, (_, i) => Math.round(i * (rows.length - 1) / Math.max(1, Math.min(7, rows.length) - 1)))));
  const labels = labelIndexes.map(index => `<text class="axis" x="${left + (index + .5) / rows.length * innerWidth}" y="${height-14}" text-anchor="middle">${escapeHtml(formatMonthYear(rows[index].period))}</text>`).join("");
  return `<svg class="gtt-line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Reported ${escapeAttr(unitLabel)} bars">${grid}${bars}${labels}</svg>`;
}

function gttPeriodSummary(rows, metricKey, unitLabel) {
  if (!rows.length) return `<div class="gtt-empty"><strong>No periods in range</strong><span>Adjust the year filters to inspect the source.</span></div>`;
  const latest = rows.at(-1), previous = rows.at(-2);
  const current = Number(latest?.[metricKey] || 0), prior = Number(previous?.[metricKey] || 0);
  const delta = prior ? (current - prior) / prior : null;
  const deltaLabel = delta === null ? "No prior comparable period" : `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}% vs ${formatMonthYear(previous.period)}`;
  return `<div class="gtt-period-stat"><span>Latest observed</span><strong>${compactTradeNumber(current)} ${unitLabel}</strong><small>${escapeHtml(formatMonthYear(latest.period))}</small></div><div class="gtt-period-stat"><span>Prior period</span><strong>${compactTradeNumber(prior)} ${unitLabel}</strong><small>${previous ? escapeHtml(formatMonthYear(previous.period)) : "—"}</small></div><div class="gtt-period-delta ${delta !== null && delta < 0 ? "negative" : ""}"><span>Period movement</span><strong>${escapeHtml(deltaLabel)}</strong></div>`;
}

function renderGttOverview(datasets) {
  const chart = document.getElementById("gtt-overview-chart");
  const ranked = document.getElementById("gtt-top-datasets");
  const freshness = document.getElementById("gtt-freshness-summary");
  const commodities = document.getElementById("gtt-top-commodities");
  const periodSummary = document.getElementById("gtt-period-summary");
  renderGttCountryProfile(state.gttAnalytics);
  renderGttTradeMap(state.gttAnalytics);
  if (!datasets.length) {
    const empty = `<div class="gtt-empty"><strong>No validated GTT records yet</strong><span>Upload a licensed GTT file or configure its connector to populate this view.</span><button type="button" data-gtt-empty-upload>Upload GTT data</button></div>`;
    chart.innerHTML = empty; ranked.innerHTML = empty; freshness.innerHTML = empty; commodities.innerHTML = empty; periodSummary.innerHTML = empty;
    document.querySelectorAll("[data-gtt-empty-upload]").forEach(button => button.addEventListener("click", () => openDataHubUpload("gtt")));
    return;
  }
  if (!state.gttAnalytics) {
    chart.innerHTML = `<div class="gtt-empty"><strong>Aggregating validated trade rows…</strong><span>Preparing monthly quantities and country rankings.</span></div>`;
    ranked.innerHTML = freshness.innerHTML = commodities.innerHTML = periodSummary.innerHTML = `<div class="gtt-empty"><strong>Loading source dimensions…</strong></div>`;
    return;
  }
  if (state.gttAnalytics.error) {
    chart.innerHTML = ranked.innerHTML = freshness.innerHTML = commodities.innerHTML = periodSummary.innerHTML = `<div class="gtt-empty"><strong>Analytics unavailable</strong><span>${escapeHtml(state.gttAnalytics.error)}</span></div>`;
    return;
  }
  const analytics = state.gttAnalytics;
  const fromYear = Number(document.getElementById("gtt-year-from").value || 0);
  const toYear = Number(document.getElementById("gtt-year-to").value || 9999);
  const trend = (analytics.trend || []).filter(row => { const year = Number(String(row.period).slice(0,4)); return year >= fromYear && year <= toYear; });
  const selectedMetric = document.getElementById("gtt-metric-filter")?.value || "quantity";
  const metricKey = selectedMetric === "value" ? "trade_value" : "quantity_mt";
  const unitLabel = selectedMetric === "value" ? "USD" : "MT";
  const metricAvailable = selectedMetric !== "value" || Number(analytics.metrics.currency_count || 0) <= 1;
  const filteredQuantity = trend.reduce((sum, row) => sum + Number(row[metricKey] || 0), 0);
  const values = {
    "gtt-kpi-datasets": metricAvailable ? `${compactTradeNumber(filteredQuantity)} ${unitLabel}` : "Unavailable",
    "gtt-kpi-rows": Number(analytics.metrics.records || 0).toLocaleString(),
    "gtt-kpi-coverage": analytics.metrics.reporter_count ?? "—",
    "gtt-kpi-latest": analytics.metrics.partner_count ?? "—",
    "gtt-kpi-quality": `${gttDatasetYear(analytics.dataset.data_start) || "—"}–${gttDatasetYear(analytics.dataset.data_end) || "—"}`,
    "gtt-nav-footer-status": analytics.dataset.dataset_name || "Source-backed analytics"
  };
  Object.entries(values).forEach(([id, value]) => { const element = document.getElementById(id); if (element) element.textContent = value; });
  document.getElementById("gtt-chart-source").textContent = !metricAvailable ? `${analytics.metrics.currency_count} source currencies · USD values kept separate` : analytics.dataset.dataset_name;
  const trendMode = state.gttChartModes.trend;
  chart.innerHTML = !metricAvailable ? `<div class="gtt-empty"><strong>Trade value is not comparable</strong><span>This source contains ${analytics.metrics.currency_count} currencies. Select Quantity or upload a single-currency source.</span></div>` : trendMode === "table" ? gttRankTable(trend.map(row => ({ label: formatMonthYear(row.period), value: row[metricKey] }))) : trendMode === "bar" ? gttBarSvg(trend, metricKey, unitLabel) : gttTrendSvg(trend, metricKey, unitLabel, trendMode);
  ranked.innerHTML = gttRankVisual(analytics.top_partners, state.gttChartModes.partners);
  freshness.innerHTML = gttRankVisual(analytics.top_reporters, state.gttChartModes.reporters);
  commodities.innerHTML = gttRankVisual(analytics.top_commodities, state.gttChartModes.commodities);
  periodSummary.innerHTML = metricAvailable ? gttPeriodSummary(trend, metricKey, unitLabel) : `<div class="gtt-empty"><strong>Movement unavailable</strong><span>Choose Quantity for a comparable period change.</span></div>`;
}

function renderGttCatalog(id, datasets) {
  const container = document.getElementById(id); if (!container) return;
  if (!datasets.length) {
    container.innerHTML = `<div class="gtt-empty"><strong>No GTT datasets in this view</strong><span>Filters never substitute or fabricate unavailable coverage.</span></div>`;
    return;
  }
  container.innerHTML = `<table><thead><tr><th>Dataset</th><th>Coverage</th><th>Frequency</th><th>Rows</th><th>Quality</th><th>Freshness</th><th></th></tr></thead><tbody>${datasets.map(item => `<tr><td><strong>${escapeHtml(item.dataset_name)}</strong><small>${escapeHtml(item.original_name || "GTT source")}</small></td><td>${escapeHtml(formatDataHubDate(item.data_start))}<br><b>${escapeHtml(formatDataHubDate(item.data_end))}</b></td><td>${escapeHtml(labelize(item.frequency || "ad_hoc"))}</td><td>${Number(item.row_count || 0).toLocaleString()}</td><td><span class="gtt-badge ${escapeAttr(item.quality_status)}">${escapeHtml(labelize(item.quality_status))}</span></td><td>${escapeHtml(item.freshness?.label || "Unknown")}</td><td><button type="button" data-gtt-open-dataset="${escapeAttr(item.id)}">Open</button></td></tr>`).join("")}</tbody></table>`;
  bindGttDatasetLinks(container);
}

function bindGttDatasetLinks(container) {
  container.querySelectorAll("[data-gtt-open-dataset]").forEach(button => button.addEventListener("click", () => {
    activateMode("datahub"); setDataHubTab("visualize");
    document.getElementById("datahub-viz-dataset").value = button.dataset.gttOpenDataset;
    loadDataHubPreview();
  }));
}

function populateGttCompare(datasets) {
  const select = document.getElementById("gtt-compare-datasets");
  const selected = new Set(Array.from(select.selectedOptions || []).map(option => option.value));
  select.innerHTML = datasets.map(item => `<option value="${escapeAttr(item.id)}" ${selected.has(item.id) ? "selected" : ""}>${escapeHtml(item.dataset_name)}</option>`).join("");
}

async function compareGttDatasets() {
  const selected = Array.from(document.getElementById("gtt-compare-datasets").selectedOptions).map(option => option.value).slice(0, 4);
  const container = document.getElementById("gtt-compare-result");
  if (selected.length < 2) { container.innerHTML = `<div class="gtt-empty"><strong>Select at least two series</strong><span>The Compare Lab supports two to four GTT datasets.</span></div>`; return; }
  container.innerHTML = `<div class="gtt-empty"><strong>Checking aligned coverage…</strong></div>`;
  try {
    const response = await fetch(`/api/data-hub/compare?dataset_ids=${encodeURIComponent(selected.join(","))}`);
    const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Comparison failed");
    container.innerHTML = `<div class="gtt-compare-cards">${payload.datasets.map(item => `<article><span>GTT SERIES</span><strong>${escapeHtml(item.dataset_name)}</strong><b>${Number(item.rows).toLocaleString()} rows</b><small>${escapeHtml(formatDataHubDate(item.data_start))} – ${escapeHtml(formatDataHubDate(item.data_end))}</small><small>${Number(item.null_rate || 0).toLocaleString(undefined, { style: "percent", maximumFractionDigits: 1 })} missing</small></article>`).join("")}</div><div class="gtt-shared-fields"><strong>${payload.join_ready ? "Candidate shared dimensions" : "No safe shared dimension detected"}</strong>${(payload.shared_fields || []).map(field => `<span>${escapeHtml(field)}</span>`).join("")}<p>${escapeHtml(payload.warning || "")}</p></div>`;
  } catch (error) { container.innerHTML = `<div class="gtt-empty"><strong>Comparison failed</strong><span>${escapeHtml(error.message)}</span></div>`; }
}

function renderGttGatedViews(datasets) {
  const groups = document.getElementById("gtt-groups-content");
  const insights = document.getElementById("gtt-insights-content");
  if (!datasets.length) {
    groups.innerHTML = `<span>MASTER DIMENSIONS REQUIRED</span><h3>Groups are waiting for GTT data</h3><p>Load validated country and HS-code dimensions before creating private or shared definitions.</p><button type="button" data-gtt-go-upload>Open uploads</button>`;
    insights.innerHTML = `<span>RELEASE 2</span><h3>Validated source required</h3><p>Load a profiled GTT dataset before generating a source-backed brief. Raw or unverified rows are never used as publishable evidence.</p><button type="button" disabled>Generate source-backed brief</button>`;
  } else {
    const groupNames = ["Asia importers", "Coal suppliers", "Top bilateral partners"];
    groups.innerHTML = `<span>RELEASE 2 · GROUPS</span><h3>Reusable research groups</h3><p>Create a local, reviewable group definition from the dimensions in the validated source. Definitions stay separate from raw records.</p><div class="gtt-release-controls"><label>Group name<input id="gtt-group-name" value="${groupNames[0]}" /></label><label>Dimension<select id="gtt-group-dimension"><option value="reporter">Reporter countries</option><option value="partner">Partner countries</option><option value="commodity">Commodities</option></select></label></div><button type="button" data-gtt-create-group>Create group</button><div id="gtt-created-groups" class="gtt-created-groups" aria-live="polite"></div>`;
    insights.innerHTML = `<span>RELEASE 2 · INSIGHTS</span><h3>Source-backed research brief</h3><p>Generate a transparent brief from validated aggregates, with coverage, units, currency caveats and the source dataset attached.</p><button type="button" data-gtt-generate-insight>Generate source-backed brief</button><div id="gtt-insight-result" class="gtt-insight-result" aria-live="polite"><span>No brief generated yet.</span></div>`;
  }
  groups.querySelectorAll("[data-gtt-go-upload]").forEach(button => button.addEventListener("click", () => setGttTab("uploads")));
  groups.querySelectorAll("[data-gtt-create-group]").forEach(button => button.addEventListener("click", () => {
    const name = document.getElementById("gtt-group-name")?.value.trim() || "Untitled group";
    const dimension = document.getElementById("gtt-group-dimension")?.selectedOptions[0]?.textContent || "Dimension";
    const created = document.getElementById("gtt-created-groups");
    if (created) created.insertAdjacentHTML("beforeend", `<span>${escapeHtml(name)} · ${escapeHtml(dimension)} · local draft</span>`);
  }));
  insights.querySelectorAll("[data-gtt-generate-insight]").forEach(button => button.addEventListener("click", () => {
    const result = document.getElementById("gtt-insight-result");
    const analytics = state.gttAnalytics;
    if (!result || !analytics || analytics.error) return;
    const topPartner = analytics.top_partners?.[0];
    const topReporter = analytics.top_reporters?.[0];
    result.innerHTML = `<strong>Validated brief</strong><p>${Number(analytics.metrics.records || 0).toLocaleString()} records report ${compactTradeNumber(analytics.metrics.quantity_mt)} MT across ${analytics.trend?.length || 0} observed periods.</p><ul><li>Largest partner by quantity: ${escapeHtml(topPartner?.label || "Not available")} (${compactTradeNumber(topPartner?.value)} MT).</li><li>Largest reporter by quantity: ${escapeHtml(topReporter?.label || "Not available")} (${compactTradeNumber(topReporter?.value)} MT).</li><li>${escapeHtml(analytics.caveats?.[0] || "Source caveat not reported.")}</li></ul><small>Dataset: ${escapeHtml(analytics.dataset.dataset_name)} · Generated from validated aggregates only.</small>`;
  }));
}

function renderGttAdmin(datasets) {
  const provider = (state.dataHubSummary?.providers || []).find(item => item.id === "gtt") || {};
  const connection = provider.connection;
  document.getElementById("gtt-admin-grid").innerHTML = `<article><span>SOURCE CONNECTOR</span><h3>${connection ? "Credentials saved" : "Not connected"}</h3><p>${connection ? `${escapeHtml(connection.connection_label)} · ${escapeHtml(connection.key_mask)}` : "Configure licensed GTT access from Uploads."}</p></article><article><span>DATA QUALITY</span><h3>${datasets.filter(item => item.quality_status === "profiled").length} profiled / ${datasets.length} total</h3><p>Schema, date coverage, nulls and duplicate rows are reported for every file.</p></article><article><span>LINEAGE</span><h3>${datasets.reduce((sum, item) => sum + Number(item.row_count || 0), 0).toLocaleString()} normalized rows</h3><p>Original file names, upload timestamps, coverage and source identity remain attached.</p></article><article><span>ENTERPRISE CONTROLS</span><h3>Not configured</h3><p>SSO, role provisioning and immutable enterprise audit logs require deployment-specific services.</p></article>`;
}

function formatDataHubDate(value) {
  if (!value) return "coverage not detected";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

// Compact month labels used on chart axes and period summaries (for example Jan-25).
function formatMonthYear(value) {
  if (value === null || value === undefined || value === "") return "—";
  const raw = String(value).trim();
  const yearMonth = raw.match(/^(\d{4})-(\d{1,2})(?:-|$)/);
  const date = yearMonth ? new Date(Date.UTC(Number(yearMonth[1]), Number(yearMonth[2]) - 1, 1)) : new Date(value);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" }).replace(" ", "-");
}

function setDataHubTab(tab) {
  document.querySelectorAll("[data-datahub-tab]").forEach(button => button.classList.toggle("active", button.dataset.datahubTab === tab));
  document.querySelectorAll("[data-datahub-panel]").forEach(panel => { panel.hidden = panel.dataset.datahubPanel !== tab; });
}

function openDataHubUpload(provider) {
  state.dataHubProvider = provider;
  document.getElementById("datahub-upload-provider").value = provider;
  document.getElementById("datahub-upload-title").textContent = `Upload ${DATA_HUB_PROVIDER_LABELS[provider]} data`;
  document.getElementById("datahub-upload-name").value = "";
  document.getElementById("datahub-file-input").value = "";
  document.getElementById("datahub-selected-file").textContent = "No file selected";
  document.getElementById("datahub-upload-message").textContent = "The file will be profiled for dates, measures, missingness and duplicates.";
  document.getElementById("datahub-upload-dialog").showModal();
}

function openDataHubApi(provider) {
  document.getElementById("datahub-api-provider").value = provider;
  document.getElementById("datahub-api-title").textContent = `Connect ${DATA_HUB_PROVIDER_LABELS[provider]} API`;
  document.getElementById("datahub-api-key").value = "";
  document.getElementById("datahub-api-message").textContent = "The browser never receives the saved key back. Provider-specific field mapping is reviewed before scheduled ingestion.";
  document.getElementById("datahub-api-dialog").showModal();
}

async function uploadDataHubDataset() {
  const file = document.getElementById("datahub-file-input").files[0];
  const provider = document.getElementById("datahub-upload-provider").value;
  const datasetName = document.getElementById("datahub-upload-name").value.trim();
  const frequency = document.getElementById("datahub-upload-frequency").value;
  const message = document.getElementById("datahub-upload-message");
  if (!file || !datasetName) { message.textContent = "Choose a file and enter a dataset name."; return; }
  message.textContent = "Uploading, normalizing and profiling…";
  const body = new FormData(); body.append("file", file);
  try {
    const url = `/api/data-hub/upload?provider=${encodeURIComponent(provider)}&dataset_name=${encodeURIComponent(datasetName)}&frequency=${encodeURIComponent(frequency)}`;
    const response = await fetch(url, { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Upload failed");
    message.textContent = `${Number(payload.row_count).toLocaleString()} rows added. Quality: ${labelize(payload.quality_status)}.`;
    await loadDataHubSummary();
    window.setTimeout(() => document.getElementById("datahub-upload-dialog").close(), 700);
  } catch (error) { message.textContent = error.message; }
}

async function saveDataHubApiConnection() {
  const message = document.getElementById("datahub-api-message");
  const body = {
    provider: document.getElementById("datahub-api-provider").value,
    endpoint_url: document.getElementById("datahub-api-endpoint").value.trim(),
    api_key: document.getElementById("datahub-api-key").value.trim(),
    connection_label: document.getElementById("datahub-api-label").value.trim() || "Default connection"
  };
  if (!body.api_key) { message.textContent = "Enter an API key."; return; }
  message.textContent = "Saving connection metadata…";
  try {
    const response = await fetch("/api/data-hub/api-connections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Connection failed");
    document.getElementById("datahub-api-key").value = "";
    message.textContent = payload.message;
    await loadDataHubSummary();
  } catch (error) { message.textContent = error.message; }
}

function renderDataHubCatalog() {
  const container = document.getElementById("datahub-catalog");
  if (!container || !state.dataHubSummary) return;
  const provider = document.getElementById("datahub-provider-filter").value;
  const datasets = (state.dataHubSummary.datasets || []).filter(item => !provider || item.provider === provider);
  if (!datasets.length) {
    container.innerHTML = `<div class="datahub-empty"><strong>No datasets in this view</strong><span>Use a provider card above to upload a file or connect an API.</span></div>`;
    return;
  }
  container.innerHTML = `<table><thead><tr><th>Dataset</th><th>Coverage</th><th>Shape</th><th>Quality</th><th>Freshness</th><th></th></tr></thead><tbody>${datasets.map(item => `<tr>
    <td><strong>${escapeHtml(item.dataset_name)}</strong><small>${escapeHtml(DATA_HUB_PROVIDER_LABELS[item.provider])} · ${escapeHtml(item.original_name)}</small></td>
    <td>${escapeHtml(formatDataHubDate(item.data_start))}<br><b>to ${escapeHtml(formatDataHubDate(item.data_end))}</b></td>
    <td>${Number(item.row_count).toLocaleString()} rows<br><small>${item.column_count} fields</small></td>
    <td><span class="datahub-quality ${escapeAttr(item.quality_status)}">${escapeHtml(labelize(item.quality_status))}</span><small>${Number(item.null_rate || 0).toLocaleString(undefined, { style: "percent", maximumFractionDigits: 0 })} missing</small></td>
    <td><span class="datahub-freshness-tag ${escapeAttr(item.freshness.status)}">${escapeHtml(item.freshness.label)}</span></td>
    <td><button type="button" data-datahub-preview="${escapeAttr(item.id)}">Preview</button></td>
  </tr>`).join("")}</tbody></table>`;
  container.querySelectorAll("[data-datahub-preview]").forEach(button => button.addEventListener("click", () => {
    setDataHubTab("visualize");
    document.getElementById("datahub-viz-dataset").value = button.dataset.datahubPreview;
    loadDataHubPreview();
  }));
}

function populateDataHubDatasetSelectors() {
  const datasets = state.dataHubSummary?.datasets || [];
  const options = datasets.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(DATA_HUB_PROVIDER_LABELS[item.provider])} · ${escapeHtml(item.dataset_name)}</option>`).join("");
  const relation = document.getElementById("datahub-relationship-datasets");
  const viz = document.getElementById("datahub-viz-dataset");
  const currentViz = viz.value;
  relation.innerHTML = options;
  viz.innerHTML = `<option value="">Choose dataset</option>${options}`;
  if (datasets.some(item => item.id === currentViz)) viz.value = currentViz;
}

function selectedDataHubDatasetIds() {
  return Array.from(document.getElementById("datahub-relationship-datasets").selectedOptions).map(option => option.value);
}

async function compareDataHubDatasets() {
  const ids = selectedDataHubDatasetIds();
  const container = document.getElementById("datahub-relationship-result");
  if (ids.length < 2) { container.innerHTML = `<div class="datahub-empty"><strong>Select at least two datasets</strong><span>Use Ctrl or Cmd to select multiple sources.</span></div>`; return; }
  container.innerHTML = `<div class="datahub-empty"><strong>Comparing source profiles…</strong></div>`;
  try {
    const response = await fetch(`/api/data-hub/compare?dataset_ids=${encodeURIComponent(ids.join(","))}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Comparison failed");
    container.innerHTML = `<div class="datahub-compare-grid">${payload.datasets.map(item => `<article><span>${escapeHtml(DATA_HUB_PROVIDER_LABELS[item.provider])}</span><strong>${escapeHtml(item.dataset_name)}</strong><b>${Number(item.rows).toLocaleString()} rows</b><small>${escapeHtml(formatDataHubDate(item.data_start))} – ${escapeHtml(formatDataHubDate(item.data_end))}</small><small>${Number(item.null_rate || 0).toLocaleString(undefined, { style: "percent", maximumFractionDigits: 0 })} missing · ${item.duplicate_rows} duplicates</small></article>`).join("")}</div><div class="datahub-key-list"><strong>${payload.join_ready ? "Candidate shared fields" : "No shared fields detected"}</strong>${payload.shared_fields.map(field => `<span>${escapeHtml(field)}</span>`).join("")}<p>${escapeHtml(payload.warning)}</p></div>`;
  } catch (error) { container.innerHTML = `<div class="datahub-empty"><strong>Comparison failed</strong><span>${escapeHtml(error.message)}</span></div>`; }
}

async function proposeDataHubRelationship() {
  const ids = selectedDataHubDatasetIds();
  const container = document.getElementById("datahub-relationship-result");
  if (ids.length < 2) { await compareDataHubDatasets(); return; }
  container.innerHTML = `<div class="datahub-empty"><strong>Building a relationship proposal…</strong><span>Checking candidate entity and time keys.</span></div>`;
  try {
    const response = await fetch("/api/data-hub/relationships/propose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset_ids: ids, question: document.getElementById("datahub-relationship-question").value.trim() }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Proposal failed");
    renderDataHubRelationshipProposal(payload);
  } catch (error) { container.innerHTML = `<div class="datahub-empty"><strong>Proposal failed</strong><span>${escapeHtml(error.message)}</span></div>`; }
}

function renderDataHubRelationshipProposal(payload) {
  const container = document.getElementById("datahub-relationship-result");
  container.innerHTML = `<div class="datahub-proposal"><header><div><span>JOIN PROPOSAL · REVIEW REQUIRED</span><strong>${escapeHtml(payload.question || "Cross-source analytical relationship")}</strong></div><button type="button" data-approve-relation="${escapeAttr(payload.id)}">Approve join proposal</button></header>${payload.links.map(link => `<article><strong>${escapeHtml(link.left_dataset)} ↔ ${escapeHtml(link.right_dataset)}</strong><small>${escapeHtml(labelize(link.status))}</small><div>${link.candidate_keys.length ? link.candidate_keys.map(key => `<span>${escapeHtml(key.left_field)} = ${escapeHtml(key.right_field)}</span>`).join("") : "<em>No safe shared key detected</em>"}</div></article>`).join("")}<footer>${payload.guardrails.map(item => `<span>${escapeHtml(item)}</span>`).join("")}<span>Approval records the reviewed proposal; it does not materialize or execute a join.</span></footer></div>`;
  container.querySelector("[data-approve-relation]").addEventListener("click", event => approveDataHubRelationship(event.currentTarget.dataset.approveRelation));
}

async function approveDataHubRelationship(id) {
  const button = document.querySelector(`[data-approve-relation="${CSS.escape(id)}"]`);
  button.disabled = true; button.textContent = "Approving…";
  try {
    const response = await fetch(`/api/data-hub/relationships/${encodeURIComponent(id)}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved: true }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Approval failed");
    button.textContent = "Proposal approved"; button.classList.add("approved");
    await loadDataHubSummary();
  } catch (error) { button.disabled = false; button.textContent = error.message; }
}

async function loadDataHubPreview() {
  const datasetId = document.getElementById("datahub-viz-dataset").value;
  if (!datasetId) return;
  const chart = document.getElementById("datahub-chart");
  chart.innerHTML = `<div class="datahub-empty"><strong>Loading preview…</strong></div>`;
  try {
    const response = await fetch(`/api/data-hub/datasets/${encodeURIComponent(datasetId)}/preview?limit=200`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Preview failed");
    state.dataHubPreview = payload;
    const columns = payload.dataset.columns || [];
    const numeric = new Set(payload.dataset.numeric_columns || []);
    document.getElementById("datahub-viz-x").innerHTML = `<option value="">Select field</option>${columns.map(column => `<option value="${escapeAttr(column)}">${escapeHtml(column)}</option>`).join("")}`;
    document.getElementById("datahub-viz-y").innerHTML = `<option value="">Select field</option>${columns.filter(column => numeric.has(column)).map(column => `<option value="${escapeAttr(column)}">${escapeHtml(column)}</option>`).join("")}`;
    document.getElementById("datahub-viz-x").value = payload.dataset.date_columns?.[0] || columns.find(column => !numeric.has(column)) || columns[0] || "";
    const preferredMeasure = (payload.dataset.numeric_columns || []).find(column =>
      /(value|quantity|volume|weight|amount|tonne|metric|price|rate)/i.test(column) &&
      !/(^|_)(id|code|year|month|day|index)($|_)/i.test(column)
    );
    document.getElementById("datahub-viz-y").value = preferredMeasure || payload.dataset.numeric_columns?.find(column => !/(^|_)(id|code|year|month|day|index)($|_)/i.test(column)) || payload.dataset.numeric_columns?.[0] || "";
    document.getElementById("datahub-chart-kicker").textContent = DATA_HUB_PROVIDER_LABELS[payload.dataset.provider];
    document.getElementById("datahub-chart-title").textContent = payload.dataset.dataset_name;
    document.getElementById("datahub-chart-subtitle").textContent = `${Number(payload.dataset.row_count).toLocaleString()} rows · ${formatDataHubDate(payload.dataset.data_start)} to ${formatDataHubDate(payload.dataset.data_end)}`;
    document.getElementById("datahub-viz-source").textContent = `${DATA_HUB_PROVIDER_LABELS[payload.dataset.provider]} · ${payload.dataset.frequency || "ad hoc"} updates`;
    document.getElementById("datahub-viz-rows").textContent = Number(payload.dataset.row_count).toLocaleString();
    document.getElementById("datahub-viz-fields").textContent = Number(columns.length).toLocaleString();
    const periodStart = formatDataHubDate(payload.dataset.data_start);
    const periodEnd = formatDataHubDate(payload.dataset.data_end);
    document.getElementById("datahub-viz-period").textContent = periodStart === periodEnd ? periodEnd : `${periodStart} – ${periodEnd}`;
    document.getElementById("datahub-viz-quality").textContent = payload.dataset.quality_status === "profiled" ? "Profiled" : "Review";
    document.getElementById("datahub-downloads").innerHTML = ["xlsx", "csv", "json"].map(format => `<a href="/api/data-hub/datasets/${encodeURIComponent(datasetId)}/export?format=${format}" download>${format.toUpperCase()}</a>`).join("");
    renderDataHubVisualization();
    renderDataHubPreviewTable();
  } catch (error) { chart.innerHTML = `<div class="datahub-empty"><strong>Preview failed</strong><span>${escapeHtml(error.message)}</span></div>`; }
}

function renderDataHubVisualization() {
  const payload = state.dataHubPreview;
  if (!payload) return;
  const xField = document.getElementById("datahub-viz-x").value;
  const yField = document.getElementById("datahub-viz-y").value;
  const type = document.getElementById("datahub-viz-type").value;
  const container = document.getElementById("datahub-chart");
  const titleNode = document.getElementById("datahub-chart-title");
  const subtitleNode = document.getElementById("datahub-chart-subtitle");
  const points = (payload.rows || []).map(row => ({ x: row[xField], y: Number(row[yField]) })).filter(point => point.x !== null && point.x !== undefined && Number.isFinite(point.y));
  if (!xField || !yField || points.length < 2) { container.innerHTML = `<div class="datahub-empty"><strong>Choose compatible X and Y fields</strong><span>A chart needs at least two valid observations.</span></div>`; return; }
  const parsedX = points.map(point => Number(point.x));
  const numericX = parsedX.every(value => Number.isFinite(value));
  const dateX = points.every(point => !Number.isNaN(Date.parse(String(point.x)))) && points.some(point => /[-/]/.test(String(point.x)));
  points.sort((a, b) => numericX ? Number(a.x) - Number(b.x) : dateX ? Date.parse(String(a.x)) - Date.parse(String(b.x)) : String(a.x).localeCompare(String(b.x)));
  const width = 900, height = 310, margin = { left: 62, right: 24, top: 24, bottom: 58 };
  const innerW = width - margin.left - margin.right, innerH = height - margin.top - margin.bottom;
  const values = points.map(point => point.y); const minY = type === "bar" ? 0 : Math.min(...values); const maxY = Math.max(...values); const spanY = maxY - minY || 1;
  const yPos = value => margin.top + innerH - ((value - minY) / spanY) * innerH;
  const xMin = numericX ? Math.min(...points.map(point => Number(point.x))) : 0;
  const xMax = numericX ? Math.max(...points.map(point => Number(point.x))) : Math.max(points.length - 1, 1);
  const xPos = (index, point) => numericX && xMax !== xMin ? margin.left + ((Number(point.x) - xMin) / (xMax - xMin)) * innerW : margin.left + (points.length === 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const ticks = [0, .25, .5, .75, 1];
  let marks = "";
  if (type === "bar") {
    const barWidth = Math.max(2, Math.min(34, innerW / points.length * .68));
    marks = points.map((point, index) => `<rect x="${xPos(index, point) - barWidth / 2}" y="${yPos(point.y)}" width="${barWidth}" height="${margin.top + innerH - yPos(point.y)}" fill="#0b5b9c"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></rect>`).join("");
  } else if (type === "scatter") {
    marks = points.map((point, index) => `<circle cx="${xPos(index, point)}" cy="${yPos(point.y)}" r="4" fill="#ef3d48" stroke="#fff" stroke-width="1.5"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></circle>`).join("");
  } else if (type === "lollipop" || type === "dot") {
    marks = points.map((point, index) => { const cx = xPos(index, point), cy = yPos(point.y); return `${type === "lollipop" ? `<line x1="${cx}" x2="${cx}" y1="${margin.top + innerH}" y2="${cy}" stroke="#8fb4d0"/>` : ""}<circle cx="${cx}" cy="${cy}" r="${type === "dot" ? 5 : 6}" fill="#ef3d48" stroke="#fff" stroke-width="1.5"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></circle>`; }).join("");
  } else {
    const path = points.map((point, index) => `${index ? "L" : "M"}${xPos(index, point).toFixed(1)},${yPos(point.y).toFixed(1)}`).join(" ");
    const steppedPath = points.map((point, index) => { if (!index) return `M${xPos(index, point).toFixed(1)},${yPos(point.y).toFixed(1)}`; const prev = points[index - 1]; return `${type === "step" ? `H${xPos(index, point).toFixed(1)} V${yPos(point.y).toFixed(1)}` : `L${xPos(index, point).toFixed(1)},${yPos(point.y).toFixed(1)}`}`; }).join(" ");
    const fill = type === "area" ? `<path d="${steppedPath} L${xPos(points.length-1, points.at(-1)).toFixed(1)},${margin.top+innerH} L${xPos(0, points[0]).toFixed(1)},${margin.top+innerH} Z" fill="#cfe1f0" opacity=".65"/>` : "";
    marks = `${fill}<path d="${steppedPath}" fill="none" stroke="#0b5b9c" stroke-width="3"/>${points.map((point, index) => `<circle cx="${xPos(index, point)}" cy="${yPos(point.y)}" r="3.5" fill="#fff" stroke="#0b5b9c" stroke-width="2"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></circle>`).join("")}`;
  }
  const labelCount = Math.min(7, points.length);
  const labelIndexes = Array.from(new Set(Array.from({ length: labelCount }, (_, index) => Math.round(index * (points.length - 1) / Math.max(1, labelCount - 1)))));
  const xLabel = dateX ? "Reporting period" : xField;
  const yLabel = yField;
  const typeNames = { line: "Trend", bar: "Category comparison", area: "Area trend", scatter: "Relationship", step: "Step trend", lollipop: "Lollipop ranking", dot: "Dot plot", histogram: "Distribution", pie: "Composition", heatmap: "Intensity map", table: "Data table" };
  if (titleNode) titleNode.textContent = `${typeNames[type] || "Chart"}: ${yField}`;
  if (subtitleNode) subtitleNode.textContent = `${yLabel} by ${xLabel} · ${points.length.toLocaleString()} valid observations · sorted for readability`;
  if (type === "table") {
    container.innerHTML = `<table class="gtt-mini-table datahub-chart-table"><thead><tr><th>${escapeHtml(xLabel)}</th><th>${escapeHtml(yLabel)}</th></tr></thead><tbody>${points.slice(0, 100).map(point => `<tr><td>${escapeHtml(String(point.x))}</td><td>${point.y.toLocaleString()}</td></tr>`).join("")}</tbody></table><small class="datahub-chart-note">Showing ${Math.min(100, points.length).toLocaleString()} of ${points.length.toLocaleString()} valid observations.</small>`;
    return;
  }
  if (type === "histogram") {
    const bins = Math.min(10, Math.max(4, Math.ceil(Math.sqrt(points.length))));
    const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
    const counts = Array.from({ length: bins }, () => 0);
    values.forEach(value => counts[Math.min(bins - 1, Math.floor((value - lo) / span * bins))]++);
    const maxCount = Math.max(...counts, 1), binW = innerW / bins;
    marks = counts.map((count, index) => { const x = margin.left + index * binW + 2, h = count / maxCount * innerH; return `<rect x="${x}" y="${margin.top + innerH - h}" width="${Math.max(2, binW - 4)}" height="${h}" fill="#0b5b9c"><title>${count} observations</title></rect>`; }).join("");
  } else if (type === "pie") {
    const total = values.reduce((sum, value) => sum + Math.max(0, value), 0) || 1; let angle = -Math.PI / 2;
    const cx = width / 2, cy = margin.top + innerH / 2, radius = Math.min(innerH, innerW) * .34;
    const colors = ["#0b5b9c", "#ef3d48", "#d8902f", "#4f8fba", "#7d65a8", "#4e9b73"];
    marks = points.slice(0, 8).map((point, index) => { const start = angle, end = angle + Math.max(0, point.y) / total * Math.PI * 2; angle = end; const x1 = cx + radius * Math.cos(start), y1 = cy + radius * Math.sin(start), x2 = cx + radius * Math.cos(end), y2 = cy + radius * Math.sin(end), large = end - start > Math.PI ? 1 : 0; return `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z" fill="${colors[index % colors.length]}" stroke="#fff" stroke-width="2"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></path>`; }).join("");
  } else if (type === "heatmap") {
    const cellW = innerW / points.length, max = Math.max(...values, 1);
    marks = points.map((point, index) => { const alpha = .12 + Math.max(0, point.y) / max * .82; return `<rect x="${margin.left + index * cellW}" y="${margin.top + innerH * .25}" width="${Math.max(1, cellW - 1)}" height="${innerH * .5}" fill="rgba(11,91,156,${alpha})"><title>${escapeHtml(String(point.x))}: ${point.y.toLocaleString()}</title></rect>`; }).join("");
  }
  if (type === "histogram" || type === "pie" || type === "heatmap") {
    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(typeNames[type])} of ${escapeAttr(yField)}">${type === "pie" ? "" : ticks.map(tick => { const y = margin.top + innerH * (1 - tick); const value = minY + spanY * tick; return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" stroke="#dce3e8"/><text x="${margin.left - 9}" y="${y + 4}" text-anchor="end">${Number(value.toFixed(2)).toLocaleString()}</text>`; }).join("")}${marks}</svg>`;
    return;
  }
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(yField)} by ${escapeAttr(xField)}">
    ${ticks.map(tick => { const y = margin.top + innerH * (1 - tick); const value = minY + spanY * tick; return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" stroke="#dce3e8"/><text x="${margin.left - 9}" y="${y + 4}" text-anchor="end">${Number(value.toFixed(2)).toLocaleString()}</text>`; }).join("")}
    ${marks}
    ${labelIndexes.map(index => `<text x="${xPos(index, points[index])}" y="${height - 30}" text-anchor="middle">${escapeHtml(dateX ? formatMonthYear(points[index].x) : String(points[index].x).slice(0, 18))}</text>`).join("")}
    <text x="${width / 2}" y="${height - 5}" text-anchor="middle" class="axis-title">${escapeHtml(xLabel)}</text>
    <text transform="translate(15 ${height / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(yLabel)}</text>
  </svg>`;
}

function renderDataHubPreviewTable() {
  const payload = state.dataHubPreview; const container = document.getElementById("datahub-preview-table");
  if (!payload?.rows?.length) { container.innerHTML = ""; return; }
  const columns = payload.dataset.columns.slice(0, 10);
  container.innerHTML = `<table><thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${payload.rows.slice(0, 20).map(row => `<tr>${columns.map(column => `<td>${escapeHtml(row[column] === null || row[column] === undefined ? "—" : String(row[column]))}</td>`).join("")}</tr>`).join("")}</tbody></table><small>Showing 20 of ${Number(payload.dataset.row_count).toLocaleString()} rows. Downloads contain the full normalized dataset.</small>`;
}

function setRiverView(view) {
  if (!new Set(["map", "table", "cards"]).has(view)) view = "map";
  state.riverView = view;
  document.querySelectorAll("[data-river-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.riverView === view);
  });
  const surface = document.getElementById("river-data-surface");
  const showSurface = state.mode === "rivers" && view !== "map";
  surface.hidden = !showSurface;
  if (state.mode === "rivers") {
    document.getElementById("map").hidden = showSurface;
    document.querySelector(".map-topbar").hidden = showSurface;
    document.querySelector(".map-key").hidden = showSurface;
  }
  document.getElementById("river-workspace-table").hidden = view !== "table";
  document.getElementById("river-workspace-cards").hidden = view !== "cards";
  if (showSurface) renderRiverWorkspace();
  else setTimeout(() => state.map.invalidateSize(), 0);
}

function riverConditionColor(status) {
  return ({ below_normal: "#c47a16", normal: "#1976a3", above_normal: "#7d3c98", unavailable: "#677883" })[status] || "#677883";
}

function riverTimestamp(value) {
  if (!value) return "Observation time unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short"
  }).format(parsed);
}

function riverObservedTimestamp(row) {
  if (row?.date_precision === "day" && row.observed_at) {
    const date = String(row.observed_at).slice(0, 10);
    const parsed = new Date(`${date}T12:00:00Z`);
    if (!Number.isNaN(parsed.getTime())) {
      return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(parsed);
    }
  }
  return riverTimestamp(row?.observed_at);
}

function riverPercentileLabel(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "Not available";
  const rounded = Math.round(Number(value));
  const mod100 = rounded % 100;
  const suffix = mod100 >= 11 && mod100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[rounded % 10] || "th";
  return `${rounded}${suffix} percentile`;
}

function riverValue(value, unit) {
  if (value === null || value === undefined || value === "") return "Not reported";
  const number = Number(value);
  if (!Number.isFinite(number)) return "Not reported";
  return `${number.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit || ""}`.trim();
}

function filteredRiverRows() {
  const waterway = document.getElementById("river-waterway-filter").value;
  const country = document.getElementById("river-country-filter").value;
  const type = document.getElementById("river-type-filter").value;
  const status = document.getElementById("river-status-filter").value;
  return state.riverRows.filter(row => {
    const haystack = `${row.station || ""} ${row.waterbody || ""} ${row.basin || ""} ${row.country || ""}`.toLowerCase();
    return (!waterway || row.waterbody === waterway)
      && (!country || row.country === country)
      && (!type || row.waterbody_type === type)
      && (!status || row.comparison_status === status)
      && (!state.riverQuery || haystack.includes(state.riverQuery));
  });
}

async function loadRiverLevels(force = false) {
  if (state.riverLoading) return;
  state.riverLoading = true;
  const status = document.getElementById("river-level-status");
  const button = document.getElementById("river-level-refresh");
  button.disabled = true;
  status.textContent = force ? "Refreshing official gauges…" : "Loading official gauges…";
  try {
    const response = await fetch(`/api/river-levels${force ? "/refresh" : ""}`, { method: force ? "POST" : "GET" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "River-level feed is unavailable");
    state.riverRows = payload.rows || [];
    state.riverSources = payload.sources || [];
    populateRiverWaterways();
    populateRiverCountries();
    updateRiverExportLink();
    renderRiverSources();
    renderRiverLevels();
    renderRiverWorkspace();
    const connected = Number(payload.connected_source_count || 0);
    const errors = (payload.errors || []).length;
    status.textContent = `${state.riverRows.length} source-backed observations · ${connected} connected sources${errors ? ` · ${errors} source warning${errors === 1 ? "" : "s"}` : ""} · refreshed ${riverTimestamp(payload.fetched_at)}`;
    document.getElementById("river-layer-count").textContent = `${state.riverRows.length} gauges`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    state.riverLoading = false;
    button.disabled = false;
  }
}

function populateRiverWaterways() {
  const select = document.getElementById("river-waterway-filter");
  const current = select.value;
  const waterways = [...new Set(state.riverRows.map(row => row.waterbody).filter(Boolean))].sort();
  select.innerHTML = `<option value="">All connected waterways</option>${waterways.map(value => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`).join("")}`;
  if (waterways.includes(current)) select.value = current;
}

function populateRiverCountries() {
  const select = document.getElementById("river-country-filter");
  const current = select.value;
  const countries = [...new Set(state.riverRows.map(row => row.country).filter(Boolean))].sort();
  select.innerHTML = `<option value="">All connected countries</option>${countries.map(value => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`).join("")}`;
  if (countries.includes(current)) select.value = current;
}

function updateRiverExportLink() {
  const params = new URLSearchParams();
  const mappings = [
    ["river-waterway-filter", "waterway"], ["river-country-filter", "country"],
    ["river-type-filter", "waterbody_type"], ["river-status-filter", "comparison_status"],
  ];
  mappings.forEach(([id, key]) => {
    const value = document.getElementById(id)?.value;
    if (value) params.set(key, value);
  });
  const link = document.getElementById("river-excel-download");
  link.href = `/api/river-levels/export.xlsx${params.toString() ? `?${params}` : ""}`;
}

function riverComparisonLabel(row) {
  return ({ below_normal: "Below normal", normal: "Within normal range", above_normal: "Above normal", unavailable: "Baseline unavailable" })[row.comparison_status] || "Baseline unavailable";
}

function renderRiverLevels() {
  if (!state.riverLayer) return;
  state.riverLayer.clearLayers();
  if (state.mode !== "rivers") return;
  const rows = filteredRiverRows();
  rows.forEach(row => {
    const lat = Number(row.latitude); const lon = Number(row.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const color = riverConditionColor(row.comparison_status);
    // Use a DOM marker rather than Leaflet's canvas circle renderer.  Canvas
    // points have a very small hit area and can sit below other canvas layers,
    // making a visible gauge unexpectedly hard to select.
    const radius = row.waterbody_type === "reservoir" ? 8 : 7;
    const marker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: "river-map-marker-shell",
        html: `<span class="river-map-marker" style="--river-marker-color:${escapeAttr(color)};--river-marker-size:${radius * 2}px" aria-hidden="true"></span>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      }),
      keyboard: true,
      title: `${row.station || "River gauge"} · ${row.waterbody || ""}`,
      riseOnHover: true,
    });
    marker.bindTooltip(`<strong>${escapeHtml(row.station)}</strong><br>${escapeHtml(row.waterbody)} · ${escapeHtml(row.country)}<br>Current ${escapeHtml(riverValue(row.level, row.level_unit))}<br>${escapeHtml(riverComparisonLabel(row))}`, { className: "weather-leaflet-tooltip", direction: "top" });
    marker.on("click", () => showRiverLevelCard(row));
    marker.addTo(state.riverLayer);
  });
  document.querySelector(".river-key-item").hidden = !rows.length;
  document.getElementById("river-workspace-count").textContent = `${rows.length} gauge${rows.length === 1 ? "" : "s"}`;
  setStatus(rows.length ? `${rows.length} river / reservoir gauges` : "No gauges match the selected filters");
}

function riverDetails(row) {
  const details = [
    ["Commercial trade role", row.trade_relevance || "Reviewed commercial navigation corridor"],
    ["Current level", riverValue(row.level, row.level_unit)],
    ["Normal / reference", riverValue(row.normal_level, row.normal_unit || row.level_unit)],
    ["Normal range", row.normal_low == null || row.normal_high == null ? "Not available from this feed" : `${riverValue(row.normal_low, row.normal_unit)} – ${riverValue(row.normal_high, row.normal_unit)}`],
    ["Difference from normal", row.difference_from_normal == null ? "Not available" : `${row.difference_from_normal > 0 ? "+" : ""}${riverValue(row.difference_from_normal, row.normal_unit || row.level_unit)}`],
    ["Percent from normal", row.percent_from_normal == null ? "Not available" : `${row.percent_from_normal > 0 ? "+" : ""}${Number(row.percent_from_normal).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`],
    ["24-hour change", row.change_24h == null ? "Not available" : `${row.change_24h > 0 ? "+" : ""}${riverValue(row.change_24h, row.change_unit)}`],
    ["7-day change", row.change_7d == null ? "Not available" : `${row.change_7d > 0 ? "+" : ""}${riverValue(row.change_7d, row.change_unit)}`],
    ["Historical percentile", riverPercentileLabel(row.historical_percentile)],
    ["Recent min–max", row.recent_min == null || row.recent_max == null ? "Not available" : `${riverValue(row.recent_min, row.level_unit)} – ${riverValue(row.recent_max, row.level_unit)}`],
    ["Trend", row.trend_value == null ? labelize(row.trend) : `${labelize(row.trend)} · ${row.trend_value > 0 ? "+" : ""}${row.trend_value} ${row.trend_unit || ""}`],
  ];
  Object.entries(row.extra_metrics || {}).forEach(([label, value]) => {
    if (value != null && value !== "") details.push([label, value]);
  });
  return details;
}

function riverSparkline(row) {
  const values = (row.history || []).map(item => Number(item.level)).filter(Number.isFinite).slice(-120);
  if (values.length < 2) return `<div class="river-sparkline-empty">Recent series not available from this feed</div>`;
  const width = 280; const height = 58;
  const min = Math.min(...values); const max = Math.max(...values); const range = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1) * width).toFixed(1)},${(height - 4 - ((value - min) / range) * (height - 8)).toFixed(1)}`).join(" ");
  return `<div class="river-sparkline"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="Recent water-level observations"><polyline points="${points}" /></svg><small>${escapeHtml(row.recent_window || `${values.length} recent observations`)}</small></div>`;
}

function showRiverLevelCard(row) {
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card", "weather-detail-card");
  card.classList.add("river-detail-card");
  const details = riverDetails(row);
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">${escapeHtml(row.waterbody_type === "reservoir" ? "RESERVOIR LEVEL" : "RIVER GAUGE")}</span>` +
    `<h2>${escapeHtml(row.station)}</h2>` +
    `<p class="detail-meta">${escapeHtml(row.waterbody)} · ${escapeHtml(row.country)} · ${escapeHtml(riverObservedTimestamp(row))}</p>` +
    `<div class="river-card-status" style="--river-status:${escapeAttr(riverConditionColor(row.comparison_status))}">${escapeHtml(riverComparisonLabel(row))}</div>` +
    riverSparkline(row) +
    `<div class="detail-grid river-detail-grid">${details.map(item => detailCell(item[0], item[1])).join("")}</div>` +
    `<p class="weather-card-summary"><strong>Comparison basis:</strong> ${escapeHtml(row.normal_basis || "Not available from this official feed")}</p>` +
    `<p class="weather-card-summary">${escapeHtml(row.quality_note || row.navigation_note || "Confirm the official source before operational use.")}</p>` +
    (row.source_url ? `<a class="official-port-link weather-source-link" href="${escapeAttr(row.source_url)}" target="_blank" rel="noopener">Open official source</a>` : "") +
    `<p class="detail-note">Source: ${escapeHtml(row.source_name)} · ${escapeHtml(row.source_method || "official publication")}. Gauge height is not channel depth or permissible draft.</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

function renderRiverWorkspace() {
  const rows = filteredRiverRows();
  document.getElementById("river-workspace-count").textContent = `${rows.length} gauge${rows.length === 1 ? "" : "s"}`;
  const low = rows.filter(row => row.comparison_status === "below_normal").length;
  const high = rows.filter(row => row.comparison_status === "above_normal").length;
  const baseline = rows.filter(row => row.normal_level != null).length;
  const countries = new Set(rows.map(row => row.country).filter(Boolean)).size;
  document.getElementById("river-kpis").innerHTML = [
    ["Visible gauges", rows.length], ["Below normal", low], ["Above normal", high], ["Baseline coverage", `${baseline} / ${rows.length}`], ["Countries", countries]
  ].map(item => `<article><span>${escapeHtml(item[0])}</span><strong>${typeof item[1] === "number" ? Number(item[1]).toLocaleString() : escapeHtml(item[1])}</strong></article>`).join("");
  const table = document.getElementById("river-workspace-table");
  table.innerHTML = rows.length ? `<table><thead><tr><th>Waterway / station</th><th>Trade role</th><th>Current</th><th>Normal</th><th>Normal range</th><th>Difference</th><th>24h / 7d</th><th>Comparison</th><th>Observed / source</th><th></th></tr></thead><tbody>${rows.map(row => `<tr class="river-status-${escapeAttr(row.comparison_status)}"><td><strong>${escapeHtml(row.waterbody)}</strong><small>${escapeHtml(row.station)} · ${escapeHtml(row.country)}</small></td><td>${escapeHtml(row.trade_relevance || "Commercial navigation corridor")}</td><td>${escapeHtml(riverValue(row.level, row.level_unit))}</td><td>${escapeHtml(riverValue(row.normal_level, row.normal_unit || row.level_unit))}</td><td>${row.normal_low == null ? "—" : `${escapeHtml(riverValue(row.normal_low, row.normal_unit))}<small>to ${escapeHtml(riverValue(row.normal_high, row.normal_unit))}</small>`}</td><td>${row.difference_from_normal == null ? "—" : `${row.difference_from_normal > 0 ? "+" : ""}${escapeHtml(riverValue(row.difference_from_normal, row.normal_unit || row.level_unit))}<small>${row.percent_from_normal > 0 ? "+" : ""}${escapeHtml(String(row.percent_from_normal))}%</small>`}</td><td>${row.change_24h == null ? "—" : `${row.change_24h > 0 ? "+" : ""}${escapeHtml(riverValue(row.change_24h, row.change_unit))}`}<small>7d ${row.change_7d == null ? "—" : `${row.change_7d > 0 ? "+" : ""}${escapeHtml(riverValue(row.change_7d, row.change_unit))}`}</small></td><td><b>${escapeHtml(riverComparisonLabel(row))}</b></td><td>${escapeHtml(riverObservedTimestamp(row))}<small>${escapeHtml(row.source_name)}</small></td><td><button type="button" data-river-id="${escapeAttr(row.id)}">Details</button></td></tr>`).join("")}</tbody></table>` : `<div class="weather-empty-state">No gauges match these filters.</div>`;
  const cards = document.getElementById("river-workspace-cards");
  cards.innerHTML = rows.length ? rows.map(row => `<article class="river-workspace-card river-status-${escapeAttr(row.comparison_status)}"><header><div><span>${escapeHtml(row.waterbody_type)} · ${escapeHtml(row.country)}</span><h2>${escapeHtml(row.station)}</h2><p>${escapeHtml(row.waterbody)}</p></div><b>${escapeHtml(riverComparisonLabel(row))}</b></header><p><strong>Trade role:</strong> ${escapeHtml(row.trade_relevance || "Commercial navigation corridor")}</p><div class="river-level-hero"><div><small>Current level</small><strong>${escapeHtml(riverValue(row.level, row.level_unit))}</strong></div><span>Observed<br>${escapeHtml(riverObservedTimestamp(row))}</span></div>${riverSparkline(row)}<div class="weather-workspace-metrics">${riverDetails(row).slice(2, 10).map(item => `<div><span>${escapeHtml(item[0])}</span><strong>${escapeHtml(item[1])}</strong></div>`).join("")}</div><p><strong>Basis:</strong> ${escapeHtml(row.normal_basis || "Not available from this official feed")}</p><button type="button" data-river-id="${escapeAttr(row.id)}">Open gauge details</button></article>`).join("") : `<div class="weather-empty-state">No gauges match these filters.</div>`;
  document.querySelectorAll("[data-river-id]").forEach(button => button.addEventListener("click", () => {
    const row = state.riverRows.find(item => item.id === button.dataset.riverId);
    if (row) showRiverLevelCard(row);
  }));
}

function renderRiverSources() {
  const container = document.getElementById("river-source-list");
  container.innerHTML = state.riverSources.map(source => `<article class="river-source-card source-${escapeAttr(source.status)}"><header><strong>${escapeHtml(source.authority)}</strong><b>${escapeHtml(source.status.replaceAll("_", " "))}</b></header><span>${escapeHtml(source.region)} · ${escapeHtml(source.waterways)}</span><p>${escapeHtml(source.metrics)}</p><small>${escapeHtml(source.availability || "Availability not assessed")}</small><small>${escapeHtml(source.access)} · ${escapeHtml(source.frequency)}</small><a href="${escapeAttr(source.url)}" target="_blank" rel="noopener">Open official source</a></article>`).join("");
}

function setCoastalWeatherEnabled(enabled) {
  state.coastalWeatherEnabled = Boolean(enabled);
  const count = document.getElementById("weather-layer-count");
  const key = document.querySelector(".weather-key-item");
  if (!state.coastalWeatherEnabled) {
    setCoastalWeatherView("map");
    state.weatherLayer.clearLayers();
    state.weatherSymbolLayer.clearLayers();
    if (state.map.hasLayer(state.weatherLayer)) state.map.removeLayer(state.weatherLayer);
    if (state.map.hasLayer(state.weatherSymbolLayer)) state.map.removeLayer(state.weatherSymbolLayer);
    count.textContent = "Off";
    key.hidden = true;
    document.getElementById("coastal-weather-status").textContent =
      "Layer is switched off.";
    const detailCard = document.getElementById("port-card");
    if (detailCard.classList.contains("weather-detail-card")) closePortCard();
    renderPorts();
    return;
  }
  state.weatherLayer.addTo(state.map);
  state.weatherSymbolLayer.addTo(state.map);
  key.hidden = false;
  focusCoastalWeatherSource();
  renderPorts();
  loadCoastalWeather();
}

function focusCoastalWeatherSource() {
  const views = {
    cyclones: [[12, 145], 2],
    india: [[20, 79], 4], indonesia: [[-2.5, 118], 5],
    malaysia: [[4.2, 109], 5], thailand: [[11, 101], 5],
    philippines: [[12.5, 122], 5], singapore: [[1.28, 103.82], 9],
    brunei: [[4.7, 114.7], 7], cambodia: [[11.3, 103.8], 6],
    myanmar: [[16, 96], 5], vietnam: [[14.5, 108.5], 5], china: [[29, 119], 4],
    sea: [[5, 111], 4], australia: [[-25, 134], 4],
    united_states: [[38, -97], 4], canada: [[50, -97], 3], japan: [[36, 138], 5],
    europe: [[51, 10], 4], south_america: [[-20, -58], 3],
    africa: [[-12, 20], 3], middle_east: [[24, 48], 4],
    major_ports: [[15, 150], 2], all: [[12, 112], 2]
  };
  const target = views[state.coastalWeatherSource];
  if (target) state.map.flyTo(target[0], target[1]);
}

function setCoastalWeatherView(view) {
  if (!new Set(["map", "table", "cards", "disruptions"]).has(view)) view = "map";
  state.coastalWeatherView = view;
  document.querySelectorAll("[data-weather-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.weatherView === view);
  });
  const surface = document.getElementById("weather-data-surface");
  const showSurface = state.mode === "weather" && view !== "map";
  surface.hidden = !showSurface;
  if (state.mode === "weather") {
    document.getElementById("map").hidden = showSurface;
    document.querySelector(".map-topbar").hidden = showSurface;
    document.querySelector(".map-key").hidden = showSurface;
  }
  document.getElementById("weather-workspace-table").hidden = view !== "table";
  document.getElementById("weather-workspace-cards").hidden = view !== "cards";
  document.getElementById("port-disruption-workspace").hidden = view !== "disruptions";
  if (view === "disruptions") loadPortDisruptions();
  else if (showSurface) renderWeatherWorkspace();
  else if (view === "map") setTimeout(() => state.map.invalidateSize(), 0);
}

async function loadPortDisruptions() {
  const workspace = document.getElementById("port-disruption-workspace");
  if (!workspace) return;
  if (!state.portDisruptions) {
    workspace.innerHTML = `<div class="weather-empty-state">Loading verified disruption sources…</div>`;
    try {
      const response = await fetch("/api/port-disruptions");
      if (!response.ok) throw new Error("Source registry is unavailable");
      state.portDisruptions = await response.json();
    } catch (error) {
      workspace.innerHTML = `<div class="weather-empty-state">${escapeHtml(error.message)}</div>`;
      return;
    }
  }
  renderPortDisruptions();
}

function renderPortDisruptions() {
  const workspace = document.getElementById("port-disruption-workspace");
  const data = state.portDisruptions;
  if (!workspace || !data) return;
  const active = Array.isArray(data.active_notices) ? data.active_notices : [];
  document.getElementById("weather-surface-subtitle").textContent =
    `Key China and Southeast Asian ports · ${active.length} verified active notices`;
  document.getElementById("weather-workspace-count").textContent =
    `${data.source_count || 0} monitored sources`;
  workspace.innerHTML = `
    <section class="disruption-methodology"><strong>Verified operating status only</strong><span>${escapeHtml(data.methodology || "")}</span></section>
    ${active.length ? `<section class="disruption-active-grid">${active.map(notice => `<article class="disruption-active-card"><b>${escapeHtml(notice.port_name)}</b><span>${escapeHtml(notice.status)}</span><p>${escapeHtml(notice.summary || "")}</p></article>`).join("")}</section>` : `<section class="disruption-empty"><h2>No verified active port-disruption notices in the connected registry</h2><p>${escapeHtml(data.disclaimer || "")}</p></section>`}
    <section class="disruption-source-grid">${(data.sources || []).map(source => `<article class="disruption-source-card">
      <header><span>${escapeHtml(source.region)}</span><b>${escapeHtml(source.evidence_type)}</b></header>
      <h2>${escapeHtml(source.authority)}</h2><p class="disruption-country">${escapeHtml(source.country)} · ${escapeHtml(source.feed_kind)}</p>
      <p>${escapeHtml(source.coverage)}</p><div class="disruption-port-tags">${(source.ports || []).map(port => `<span>${escapeHtml(port)}</span>`).join("")}</div>
      <a href="${escapeAttr(source.url)}" target="_blank" rel="noopener">Open source</a>
    </article>`).join("")}</section>`;
}

function updateCoastalWeatherDownload() {
  const source = state.coastalWeatherSource;
  const href = source === "cyclones"
    ? "/api/weather/cyclones/export.csv"
    : source === "india"
    ? "/api/imd/coastal-weather/export.csv"
    : source === "indonesia"
      ? "/api/bmkg/marine-weather/export.csv"
      : `/api/coastal-weather/export.csv?source=${encodeURIComponent(source)}`;
  document.getElementById("coastal-weather-download").href = href;
  const report = document.getElementById("coastal-weather-port-report");
  report.hidden = source === "cyclones";
  if (source !== "cyclones") {
    report.href = `/api/coastal-weather/port-report.xlsx?source=${encodeURIComponent(source)}`;
  }
}

function imdForecastDay() {
  return Math.min(5, Math.floor(state.coastalWeatherHours / 24) + 1);
}

async function requestCoastalWeather(provider, force) {
  let endpoint;
  if (provider === "cyclone") {
    endpoint = `/api/weather/cyclones${force ? "/refresh" : ""}`;
  } else if (provider === "imd") {
    endpoint = `/api/imd/coastal-weather${force ? "/refresh" : ""}?day=${imdForecastDay()}`;
  } else if (provider === "bmkg") {
    endpoint = `/api/bmkg/marine-weather${force ? "/refresh" : ""}?hours=${state.coastalWeatherHours}`;
  } else if (provider === "major") {
    const countryNames = {
      australia: "Australia", united_states: "United States", canada: "Canada", japan: "Japan"
    };
    const regionNames = {
      europe: "Europe", south_america: "South America", africa: "Africa", middle_east: "Middle East"
    };
    const country = countryNames[state.coastalWeatherSource]
      ? `&country=${encodeURIComponent(countryNames[state.coastalWeatherSource])}`
      : "";
    const region = regionNames[state.coastalWeatherSource]
      ? `&region=${encodeURIComponent(regionNames[state.coastalWeatherSource])}`
      : "";
    endpoint = `/api/major-port-weather${force ? "/refresh" : ""}?hours=${state.coastalWeatherHours}${country}${region}`;
  } else {
    const country = new Set(["malaysia", "thailand", "philippines", "singapore", "brunei", "cambodia", "myanmar", "vietnam", "china"])
      .has(state.coastalWeatherSource)
      ? `&country=${encodeURIComponent(state.coastalWeatherSource[0].toUpperCase() + state.coastalWeatherSource.slice(1))}`
      : "";
    endpoint = `/api/sea/marine-weather${force ? "/refresh" : ""}?hours=${state.coastalWeatherHours}${country}`;
  }
  const response = await fetch(endpoint, { method: force ? "POST" : "GET" });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${provider.toUpperCase()} request failed (${response.status})`);
  }
  return response.json();
}

function normalizeImdWeather(row) {
  if (row.location_id && row.location_type) return row;
  return {
    ...row,
    provider_code: "imd",
    provider: "IMD",
    country: "India",
    location_type: "water",
    location_id: `imd-area-${row.zone_id}`,
    location_name: row.zone_name,
    valid_from: row.valid_date,
    weather_condition: row.rainfall_category,
    weather_description: row.summary,
    warning_description: row.severity === "warning" ? row.summary : null,
    wind_speed_min_display: row.wind_speed_min_kmph,
    wind_speed_max_display: row.wind_speed_max_kmph,
    wind_speed_unit: "km/h"
  };
}

async function loadCoastalWeather(force = false) {
  if (!state.coastalWeatherEnabled) return;
  if (state.coastalWeatherLoading) {
    state.coastalWeatherPendingReload = true;
    return;
  }
  state.coastalWeatherLoading = true;
  const status = document.getElementById("coastal-weather-status");
  const refreshButton = document.getElementById("coastal-weather-refresh");
  refreshButton.disabled = true;
  status.textContent = force
    ? "Refreshing official coastal forecasts…"
    : "Loading official coastal forecasts…";
  const providers = state.coastalWeatherSource === "all"
    ? ["cyclone", "imd", "bmkg", "sea", "major"]
    : state.coastalWeatherSource === "both"
      ? ["imd", "bmkg"]
      : state.coastalWeatherSource === "india"
        ? ["imd"]
        : state.coastalWeatherSource === "indonesia"
          ? ["bmkg"]
          : state.coastalWeatherSource === "cyclones"
            ? ["cyclone"]
          : new Set(["australia", "united_states", "canada", "japan", "europe", "south_america", "africa", "middle_east", "major_ports"]).has(state.coastalWeatherSource)
            ? ["major"]
          : ["sea"];
  try {
    const results = await Promise.allSettled(
      providers.map(provider => requestCoastalWeather(provider, force))
    );
    const rows = [];
    const updated = [];
    const errors = [];
    const staleProviders = [];
    results.forEach((result, index) => {
      const provider = providers[index];
      if (result.status === "rejected") {
        errors.push(result.reason?.message || `${provider.toUpperCase()} unavailable`);
        return;
      }
      const payload = result.value;
      const payloadRows = Array.isArray(payload.rows) ? payload.rows : [];
      rows.push(...(provider === "imd" ? payloadRows.map(normalizeImdWeather) : payloadRows));
      if (payload.fetched_at) updated.push(new Date(payload.fetched_at).getTime());
      if (payload.stale || payload.last_error) {
        const label = provider === "imd" ? "India / IMD" : provider.toUpperCase();
        const age = Number.isFinite(Number(payload.refresh_age_hours))
          ? ` cached ${Number(payload.refresh_age_hours).toFixed(1)} h ago`
          : " cache status unknown";
        staleProviders.push(`${label}${age}${payload.last_error ? ` · refresh issue: ${payload.last_error}` : ""}`);
      }
    });
    if (!rows.length) throw new Error(errors.join("; ") || "No published weather values returned");
    state.coastalWeatherRows = rows;
    state.weatherPortTierCache.clear();
    renderCoastalWeather();
    renderWeatherWorkspace();
    const visible = weatherVisibleRows();
    const portCount = visible.filter(row => row.location_type === "port").length;
    const stormCount = visible.filter(row => row.location_type === "storm").length;
    const areaCount = visible.filter(row => row.location_type === "water").length;
    const latest = updated.length ? new Date(Math.max(...updated)).toLocaleString() : "time unavailable";
    status.textContent = `${stormCount} active cyclones · ${areaCount} forecast areas · ${portCount} port forecasts · updated ${latest}` +
      (staleProviders.length ? ` · STALE: ${staleProviders.join("; ")}` : "") +
      (errors.length ? ` · ${errors.join("; ")}` : "");
  } catch (error) {
    status.textContent = `Weather unavailable: ${error.message}`;
    state.weatherLayer.clearLayers();
    state.weatherSymbolLayer.clearLayers();
    document.getElementById("weather-layer-count").textContent = "Unavailable";
  } finally {
    state.coastalWeatherLoading = false;
    refreshButton.disabled = false;
    if (state.coastalWeatherPendingReload && state.coastalWeatherEnabled) {
      state.coastalWeatherPendingReload = false;
      setTimeout(() => loadCoastalWeather(force), 0);
    }
  }
}

function hasRainSignal(row) {
  return Boolean(row.rainfall_category) || /hujan|rain|badai|storm/i.test(
    `${row.weather_condition || ""} ${row.weather_description || ""}`
  );
}

function weatherAdverseCondition(row) {
  const text = [
    row.warning_description,
    row.weather_condition,
    row.weather_description,
    row.summary,
    row.station_remark
  ].filter(Boolean).join(" ");
  const hazards = [];
  if (/\btsunami\b/i.test(text)) hazards.push("Tsunami");
  if (/\btyphoon\b|\btopan\b/i.test(text)) hazards.push("Typhoon");
  if (/\b(?:tropical\s+)?cyclone\b|\bsiklon(?:\s+tropis)?\b/i.test(text)) hazards.push("Cyclone");
  return Array.from(new Set(hazards)).join(" · ");
}

function weatherWarningReason(row) {
  const condition = weatherAdverseCondition(row);
  return condition ? `${condition} warning` : "";
}

function portWeatherAlertReason(row) {
  return row.location_type === "port" ? weatherWarningReason(row) : "";
}

function weatherVisibleRows() {
  const params = state.coastalWeatherParameters;
  return state.coastalWeatherRows.filter(row => (
    (state.coastalWeatherLocationType === "all" || row.location_type === state.coastalWeatherLocationType)
  )).filter(row => (
    state.coastalWeatherDataClass === "all" || row.data_class === state.coastalWeatherDataClass
  )).filter(row => (
    state.coastalWeatherPortStatus === "all" || row.port_operational_status === state.coastalWeatherPortStatus
  )).filter(row => (
    (row.location_type === "storm" && params.has("cyclone")) ||
    (row.location_type === "port" && params.size > 0) ||
    (params.has("rain") && hasRainSignal(row)) ||
    (params.has("wind") && (
      row.wind_speed_max_kmph != null || row.wind_speed_max_kn != null || row.gust_kmph != null
    )) ||
    (params.has("wave") && row.wave_height_max_m != null) ||
    (params.has("warning") && Boolean(weatherWarningReason(row))) ||
    (params.has("current") && row.current_speed_max_source != null) ||
    (params.has("visibility") && row.visibility_source != null) ||
    (params.has("air") && (
      row.temperature_min_c != null || row.temperature_max_c != null ||
      row.humidity_min_pct != null || row.humidity_max_pct != null
    )) ||
    (params.has("tide") && (row.high_tide_height_m != null || row.low_tide_height_m != null))
  ));
}

function weatherColor(severity) {
  if (severity === "warning") return "#c93036";
  if (severity === "advisory") return "#d68a1d";
  return "#2c91b4";
}

function weatherValue(value, suffix = "") {
  return value == null
    ? "Not quantified"
    : `${Number(value).toLocaleString()}${suffix ? ` ${suffix}` : ""}`;
}

function weatherRange(minimum, maximum, unit) {
  if (maximum == null && minimum == null) return "Not quantified";
  if (minimum == null || Number(minimum) === Number(maximum)) return weatherValue(maximum ?? minimum, unit);
  return `${weatherValue(minimum)}–${weatherValue(maximum, unit)}`;
}

function weatherPeriod(row) {
  if (row.valid_from && row.valid_to) {
    const parseForecastTime = value => new Date(String(value).replace(" UTC", "Z").replace(" ", "T"));
    return `${parseForecastTime(row.valid_from).toLocaleString()} – ${parseForecastTime(row.valid_to).toLocaleString()}`;
  }
  return row.valid_date || row.source_issue_time || "Latest published forecast";
}

function weatherWindRange(row) {
  return row.wind_speed_min_kn != null || row.wind_speed_max_kn != null
    ? weatherRange(row.wind_speed_min_kn, row.wind_speed_max_kn, "kt")
    : weatherRange(row.wind_speed_min_kmph, row.wind_speed_max_kmph, "km/h");
}

function weatherDirectionRange(from, to, mode = "from") {
  const start = String(from || "").trim();
  const end = String(to || "").trim();
  if (!start && !end) return "";
  const prefix = mode === "toward" ? "Toward" : "From";
  if (!start || !end) return `${prefix} ${start || end}`;
  if (start.toLowerCase() === end.toLowerCase()) {
    return `${prefix} ${start} (steady direction)`;
  }
  return `${prefix} ${start}–${end}`;
}

function coastalPortDisplayName(row) {
  const name = String(row.location_name || row.zone_name || "Unknown").trim();
  if (row.location_type !== "port") return name;
  return name
    .replace(/\s+(?:coal|dry[- ]?bulk|container|oil|lng)\s+terminal\b/gi, "")
    .replace(/\s+\((?:coal|dry[- ]?bulk|container|oil|lng)\s+terminal\)$/i, "")
    .trim() || name;
}

function coastalWeatherTooltip(row) {
  const warningReason = weatherWarningReason(row);
  const warning = state.coastalWeatherParameters.has("warning") && warningReason
    ? `<div><span>Warning</span><strong>${escapeHtml(warningReason)}</strong></div>`
    : "";
  const rain = state.coastalWeatherParameters.has("rain")
    && (row.weather_condition || row.rainfall_category)
    ? `<div><span>Weather</span><strong>${escapeHtml(row.weather_condition || row.rainfall_category)}</strong></div>`
    : "";
  const wind = state.coastalWeatherParameters.has("wind") && (
    row.wind_speed_min_kn != null || row.wind_speed_max_kn != null ||
    row.wind_speed_min_kmph != null || row.wind_speed_max_kmph != null || row.gust_kmph != null
  )
    ? `<div><span>Wind</span><strong>${weatherWindRange(row)}</strong></div>`
    : "";
  const waves = state.coastalWeatherParameters.has("wave") && (row.wave_height_min_m != null || row.wave_height_max_m != null)
    ? `<div><span>Wave height</span><strong>${weatherRange(row.wave_height_min_m, row.wave_height_max_m, "m")}</strong></div>`
    : "";
  const current = state.coastalWeatherParameters.has("current") && row.current_speed_max_source != null
    ? `<div><span>Current (source)</span><strong>${weatherRange(row.current_speed_min_source, row.current_speed_max_source, "")}</strong></div>`
    : "";
  const visibility = state.coastalWeatherParameters.has("visibility") && row.visibility_source != null
    ? `<div><span>Visibility</span><strong>${weatherValue(row.visibility_source, row.visibility_documented_unit || "")}</strong></div>`
    : "";
  const air = state.coastalWeatherParameters.has("air")
    ? (row.temperature_min_c != null || row.temperature_max_c != null
        ? `<div><span>Temperature</span><strong>${weatherRange(row.temperature_min_c, row.temperature_max_c, "°C")}</strong></div>` : "") +
      (row.humidity_min_pct != null || row.humidity_max_pct != null
        ? `<div><span>Humidity</span><strong>${weatherRange(row.humidity_min_pct, row.humidity_max_pct, "%")}</strong></div>` : "")
    : "";
  const tides = state.coastalWeatherParameters.has("tide")
    ? (row.high_tide_height_m != null
        ? `<div><span>High tide</span><strong>${weatherValue(row.high_tide_height_m, "m")}</strong></div>` : "") +
      (row.low_tide_height_m != null
        ? `<div><span>Low tide</span><strong>${weatherValue(row.low_tide_height_m, "m")}</strong></div>` : "")
    : "";
  const source = row.source_url
    ? `<a href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener">Open ${escapeHtml(row.provider || "official")} source</a>`
    : "No quantified source entry";
  return `
    <div class="weather-tooltip">
      <span class="weather-tooltip-kicker">${escapeHtml(row.provider || "OFFICIAL")} · ${escapeHtml((row.location_type || "area").toUpperCase())}</span>
      <h3>${escapeHtml(coastalPortDisplayName(row))}</h3>
      ${warning}${rain}${wind}${waves}${current}${visibility}${air}${tides}
      <small>${escapeHtml(weatherPeriod(row))}</small>
      <small>${source} · forecast, not for navigation</small>
    </div>`;
}

function weatherDominantSignal(row) {
  const animated = state.coastalWeatherAnimated ? " animated" : "";
  const locationName = row.location_name || row.zone_name || (row.location_type === "port" ? "Port" : "Marine area");
  if (row.location_type === "storm" && state.coastalWeatherParameters.has("cyclone")) {
    return {
      kind: "cyclone",
      label: `${row.location_name}: ${row.alert_level || "active"} tropical-cyclone alert`,
      html: `<span class="weather-cyclone${animated} alert-${escapeAttr(String(row.alert_level || "green").toLowerCase())}" title="${escapeAttr(`${row.location_name}: active cyclone`) }">🌀</span>`
    };
  }
  const warningReason = weatherWarningReason(row);
  if (state.coastalWeatherParameters.has("warning") && warningReason) {
    return {
      kind: "warning",
      label: `${warningReason}: ${locationName}`,
      html: `<span class="weather-warning-dot${animated}" title="${escapeAttr(`${locationName}: ${warningReason}`)}"></span>`
    };
  }
  if (state.coastalWeatherParameters.has("rain") && hasRainSignal(row)) {
    return {
      kind: "rain",
      label: "Rain forecast",
      html: `<span class="weather-rain${animated}" title="Rain forecast"><i></i><i></i><i></i></span>`
    };
  }
  const wave = Number(row.wave_height_max_m || 0);
  const wind = Number(row.wind_speed_max_kn || row.wind_speed_max_kmph || row.gust_kmph || 0);
  if (state.coastalWeatherParameters.has("wave") && wave >= 2.5) {
    return {
      kind: "wave",
      label: "High waves",
      html: `<span class="weather-wave${animated}" title="High waves"><i></i><i></i></span>`
    };
  }
  if (state.coastalWeatherParameters.has("wind") && wind >= 20) {
    return {
      kind: "wind",
      label: "Strong wind",
      html: `<span class="weather-wind${animated}" title="Strong wind"><i></i><i></i><i></i></span>`
    };
  }
  if (state.coastalWeatherParameters.has("current") && row.current_speed_max_source != null) {
    return {
      kind: "current",
      label: "Ocean current",
      html: `<span class="weather-current${animated}" title="Ocean current"><i></i><i></i></span>`
    };
  }
  if (state.coastalWeatherParameters.has("visibility") && row.visibility_source != null) {
    return {
      kind: "visibility",
      label: "Visibility forecast",
      html: `<span class="weather-data-symbol weather-visibility-symbol" title="Visibility forecast">VIS</span>`
    };
  }
  if (state.coastalWeatherParameters.has("tide") && (row.high_tide_height_m != null || row.low_tide_height_m != null)) {
    return {
      kind: "tide",
      label: "Tide forecast",
      html: `<span class="weather-data-symbol weather-tide-symbol" title="Tide forecast">↕</span>`
    };
  }
  if (state.coastalWeatherParameters.has("air") && (row.temperature_min_c != null || row.temperature_max_c != null)) {
    return {
      kind: "air",
      label: "Air conditions",
      html: `<span class="weather-data-symbol weather-air-symbol" title="Temperature and humidity">°C</span>`
    };
  }
  if (state.coastalWeatherParameters.has("wave") && row.wave_height_max_m != null) {
    return {
      kind: "wave",
      label: "Wave forecast",
      html: `<span class="weather-wave${animated}" title="Wave forecast"><i></i><i></i></span>`
    };
  }
  if (state.coastalWeatherParameters.has("wind") && wind) {
    return {
      kind: "wind",
      label: "Wind forecast",
      html: `<span class="weather-wind${animated}" title="Wind forecast"><i></i><i></i><i></i></span>`
    };
  }
  return null;
}

function weatherSymbolHtml(row) {
  const signal = weatherDominantSignal(row);
  if (!signal) return "";
  const showRain = state.coastalWeatherParameters.has("rain") && hasRainSignal(row);
  const secondaryRain = showRain && signal.kind !== "rain"
    ? `<span class="weather-secondary-signal" aria-label="Rain forecast"><span class="weather-rain${state.coastalWeatherAnimated ? " animated" : ""}" title="Rain forecast"><i></i><i></i><i></i></span></span>`
    : "";
  return `<div class="weather-symbols weather-symbol-single signal-${signal.kind}${secondaryRain ? " has-secondary-rain" : ""} severity-${row.severity}" aria-label="${escapeAttr(signal.label)}">${signal.html}${secondaryRain}</div>`;
}

function weatherSignalIsNoteworthy(row) {
  const wave = Number(row.wave_height_max_m || 0);
  const wind = Number(row.wind_speed_max_kn || row.wind_speed_max_kmph || row.gust_kmph || 0);
  return hasRainSignal(row) || Boolean(weatherWarningReason(row)) || wave > 2.5 || wind >= 20;
}

function weatherDetailEntries(row) {
  if (row.location_type === "storm") {
    const ports = Array.isArray(row.affected_ports) ? row.affected_ports : [];
    const portText = ports.length
      ? ports.slice(0, 12).map(port => `${port.port_name}${port.country ? ` (${port.country})` : ""} · ${Number(port.distance_to_forecast_track_km).toLocaleString()} km`).join("; ")
      : "No catalogue ports inside the current forecast-track corridor";
    return [
      { label: "Ocean / sea", value: [row.basin, row.ocean_or_sea].filter(Boolean).join(" · ") },
      { label: "Current position", value: `${Number(row.latitude).toFixed(2)}°, ${Number(row.longitude).toFixed(2)}°` },
      { label: "Intensity", value: row.weather_condition || "Tropical cyclone" },
      { label: "Maximum wind", value: row.max_wind_kn == null ? "Not published" : `${Number(row.max_wind_kn).toLocaleString()} kt · ${Number(row.max_wind_kmph).toLocaleString()} km/h` },
      { label: "Moving", value: row.movement_bearing_deg == null ? row.movement_direction : `${row.movement_direction} · ${Number(row.movement_bearing_deg).toFixed(0)}°` },
      { label: "Possible landfall / coastal impact", value: row.possible_landfall },
      { label: "Affected countries", value: Array.isArray(row.affected_countries) && row.affected_countries.length ? row.affected_countries.join(", ") : "None identified in current alert" },
      { label: `Ports in ${Number(row.impact_radius_km).toLocaleString()} km corridor`, value: portText },
      { label: "Port-impact method", value: row.impact_methodology },
      { label: "Originating forecast agency", value: row.source_agency || "RSMC / TCWC" },
      { label: "Forecast basis", value: row.forecast_basis },
    ].filter(item => item.value && item.value !== "Not quantified");
  }
  const details = [];
  const add = (label, value) => {
    if (value !== null && value !== undefined && String(value).trim() && value !== "Not quantified") {
      details.push({ label, value: String(value) });
    }
  };
  add("Weather", row.weather_condition || row.rainfall_category);
  add("Port operating status", row.location_type === "port" ? (row.port_operational_status || "Not reported") : null);
  add("Operational notice", row.operational_notice);
  add("Next 24 hours", row.forecast_24h);
  add("Next 72 hours", row.forecast_72h);
  add("Adverse weather", weatherAdverseCondition(row) || "None reported");
  if (row.wind_speed_min_kn != null || row.wind_speed_max_kn != null || row.wind_speed_min_kmph != null || row.wind_speed_max_kmph != null) {
    add("Wind speed", weatherWindRange(row));
  }
  add("Maximum gust", row.gust_kmph == null ? null : weatherValue(row.gust_kmph, "km/h"));
  add("Wind direction", weatherDirectionRange(row.wind_direction_from, row.wind_direction_to, "from"));
  if (row.wave_height_min_m != null || row.wave_height_max_m != null) {
    add("Wave height", weatherRange(row.wave_height_min_m, row.wave_height_max_m, "m"));
  }
  add("Wave category", row.wave_category);
  add("Wave description", row.wave_description);
  add("Port weather risk", row.weather_risk_level ? `${row.weather_risk_level} · score ${row.weather_risk_score}` : null);
  add("Operational impact", Array.isArray(row.operational_impacts) ? row.operational_impacts.join("; ") : row.operational_impacts);
  if (row.current_speed_min_source != null || row.current_speed_max_source != null) {
    add(`Current speed (${row.provider || "official"} source)`, weatherRange(row.current_speed_min_source, row.current_speed_max_source, ""));
  }
  add("Current direction", weatherDirectionRange(row.current_direction_from, row.current_direction_to, "toward"));
  add("Visibility", row.visibility_source == null ? null : weatherValue(row.visibility_source, row.visibility_documented_unit || ""));
  add("Official marine area", row.marine_area);
  add("Offshore wave area", row.offshore_marine_area);
  add("Forecast basis", row.forecast_basis);
  add("Data classification", row.data_class ? row.data_class.replaceAll("_", " ") : null);
  add("Data confidence", row.data_confidence ? `${row.data_confidence} · quality ${row.quality_score}/100` : null);
  add("Freshness", row.freshness_status ? `${row.freshness_status}${row.freshness_age_hours == null ? "" : ` · ${row.freshness_age_hours} h`}` : null);
  add("Source authority", row.source_authority);
  if (row.temperature_min_c != null || row.temperature_max_c != null) {
    add("Temperature", weatherRange(row.temperature_min_c, row.temperature_max_c, "°C"));
  }
  if (row.humidity_min_pct != null || row.humidity_max_pct != null) {
    add("Humidity", weatherRange(row.humidity_min_pct, row.humidity_max_pct, "%"));
  }
  add("High tide", row.high_tide_height_m == null ? null : `${weatherValue(row.high_tide_height_m, "m")} · ${row.high_tide_time || "time unavailable"}`);
  add("Low tide", row.low_tide_height_m == null ? null : `${weatherValue(row.low_tide_height_m, "m")} · ${row.low_tide_time || "time unavailable"}`);
  add("Station note", row.station_remark);
  return details;
}

function weatherWorkspaceRows() {
  const query = state.coastalWeatherQuery;
  return state.coastalWeatherRows
    .filter(row => state.coastalWeatherLocationType === "all" || row.location_type === state.coastalWeatherLocationType)
    .filter(row => state.coastalWeatherDataClass === "all" || row.data_class === state.coastalWeatherDataClass)
    .filter(row => state.coastalWeatherPortStatus === "all" || row.port_operational_status === state.coastalWeatherPortStatus)
    .filter(row => !query || `${row.location_name || row.zone_name || ""} ${row.country || ""} ${row.weather_condition || ""} ${row.basin || ""} ${row.ocean_or_sea || ""} ${(row.affected_countries || []).join?.(" ") || ""}`.toLowerCase().includes(query))
    .sort((a, b) => {
      const severityRank = { warning: 0, advisory: 1, normal: 2 };
      const adverseRank = row => weatherAdverseCondition(row) ? 0 : 1;
      return adverseRank(a) - adverseRank(b) ||
        (severityRank[a.severity] ?? 3) - (severityRank[b.severity] ?? 3) ||
        String(a.country || "").localeCompare(String(b.country || "")) ||
        String(a.location_name || a.zone_name || "").localeCompare(String(b.location_name || b.zone_name || ""));
    });
}

function renderWeatherWorkspace() {
  const table = document.getElementById("weather-workspace-table");
  const cards = document.getElementById("weather-workspace-cards");
  if (!table || !cards) return;
  const rows = weatherWorkspaceRows();
  const typeLabel = state.coastalWeatherLocationType === "port"
    ? "ports" : state.coastalWeatherLocationType === "water" ? "marine areas" : state.coastalWeatherLocationType === "storm" ? "cyclones and typhoons" : "ports, marine areas and tropical cyclones";
  document.getElementById("weather-workspace-count").textContent = rows.length && rows.every(row => row.location_type === "storm")
    ? `${rows.length.toLocaleString()} active storms`
    : `${rows.length.toLocaleString()} forecasts`;
  document.getElementById("weather-surface-subtitle").textContent =
    `${typeLabel} · ${state.coastalWeatherHours ? `+${state.coastalWeatherHours} hours` : "current forecast"}`;
  const commonColumns = [
    ["Location", row => coastalPortDisplayName(row)],
    ["Country", row => row.country || "—"],
    ["Type", row => row.location_type === "port" ? "Port" : "Marine area"],
    ["Forecast area", row => row.marine_area || "—"],
    ["Condition", row => row.weather_condition || row.rainfall_category || "—"],
    ["Wind", row => (row.wind_speed_max_kn != null || row.wind_speed_max_kmph != null) ? weatherWindRange(row) : "—"],
    ["Waves", row => row.wave_height_max_m == null ? "—" : weatherRange(row.wave_height_min_m, row.wave_height_max_m, "m")],
    ["Port risk", row => row.weather_risk_level || "—"],
    ["Port status", row => row.location_type === "port" ? (row.port_operational_status || "Not reported") : "—"],
    ["Data basis", row => row.data_class ? row.data_class.replaceAll("_", " ") : "—"],
    ["Freshness", row => row.freshness_status || "unknown"],
    ["Adverse weather", row => weatherAdverseCondition(row) || "—"]
  ];
  const portColumns = [
    ["Current", row => row.current_speed_max_source == null ? "—" : weatherRange(row.current_speed_min_source, row.current_speed_max_source, ""), row => row.current_speed_max_source != null],
    ["Temperature", row => row.temperature_max_c == null ? "—" : weatherRange(row.temperature_min_c, row.temperature_max_c, "°C"), row => row.temperature_max_c != null],
    ["Tide", row => row.high_tide_height_m == null ? "—" : weatherValue(row.high_tide_height_m, "m"), row => row.high_tide_height_m != null]
  ].filter(([, , hasValue]) => rows.some(hasValue)).map(([label, value]) => [label, value]);
  const cycloneColumns = [
    ["Storm", row => row.location_name || "Unknown"],
    ["Ocean / sea", row => row.ocean_or_sea || row.basin || "—"],
    ["Alert", row => row.alert_level || "—"],
    ["Intensity", row => row.weather_condition || "—"],
    ["Maximum wind", row => row.max_wind_kn == null ? "—" : `${Number(row.max_wind_kn).toLocaleString()} kt`],
    ["Moving", row => row.movement_direction || "—"],
    ["Possible impact area", row => (row.affected_countries || []).join(", ") || "Offshore / not identified"],
    ["Ports in corridor", row => String(row.affected_port_count ?? 0)],
    ["Updated", row => row.issued_at ? new Date(row.issued_at).toLocaleString() : "—"]
  ];
  const cycloneOnly = state.coastalWeatherLocationType === "storm" || state.coastalWeatherSource === "cyclones";
  const columns = cycloneOnly ? cycloneColumns : state.coastalWeatherLocationType === "port" ? [...commonColumns, ...portColumns] : commonColumns;
  table.innerHTML = rows.length ? `<table><thead><tr>${columns.map(([label]) => `<th>${escapeHtml(label)}</th>`).join("")}<th></th></tr></thead><tbody>${rows.map(row => `<tr class="severity-${weatherAdverseCondition(row) ? "warning" : "normal"}">${columns.map(([, value]) => `<td>${escapeHtml(value(row))}</td>`).join("")}<td><button type="button" data-weather-location="${escapeAttr(row.location_id)}">Details</button></td></tr>`).join("")}</tbody></table>` : `<div class="weather-empty-state">No forecasts match these filters.</div>`;
  cards.innerHTML = rows.length ? rows.slice(0, 160).map(row => {
    const details = weatherDetailEntries(row);
    const warning = weatherWarningReason(row);
    const displaySeverity = warning ? "warning" : "normal";
    const statusLabel = row.alert_level || (row.location_type === "port" ? row.port_operational_status : null) || row.weather_risk_level || displaySeverity;
    const locationType = row.location_type === "storm" ? "TROPICAL CYCLONE" : row.location_type === "port" ? "PORT" : "MARINE AREA";
    return `<article class="weather-workspace-card severity-${displaySeverity}">
      <header><div><span>${escapeHtml(row.provider || "Official")} · ${locationType}</span><h2>${escapeHtml(coastalPortDisplayName(row))}</h2></div><b>${escapeHtml(statusLabel)}</b></header>
      <p class="weather-workspace-period">${escapeHtml(weatherPeriod(row))}</p>
      <p class="weather-workspace-provenance">${escapeHtml((row.data_class || "official forecast").replaceAll("_", " "))} · ${escapeHtml(row.data_confidence || "Confidence unknown")} confidence · ${escapeHtml(row.freshness_status || "freshness unknown")}</p>
      ${warning ? `<p class="weather-workspace-warning">${escapeHtml(warning)}</p>` : ""}
      ${row.location_type === "storm" ? `<div class="cyclone-card-motion" aria-label="Forecast movement ${escapeAttr(row.movement_direction || "unknown")}"><span>🌀</span><i></i><b>➤</b><small>${escapeHtml(row.movement_direction || "Direction not published")}</small></div>` : ""}
      <div class="weather-workspace-metrics">${details.map(item => `<div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join("")}</div>
      ${row.location_type !== "storm" && (row.weather_description || row.summary) ? `<p class="weather-workspace-summary">${escapeHtml(row.weather_description || row.summary)}</p>` : ""}
      <button type="button" data-weather-location="${escapeAttr(row.location_id)}">${row.location_type === "storm" ? "Open cyclone details" : "Open detailed forecast"}</button>
    </article>`;
  }).join("") : `<div class="weather-empty-state">No forecasts match these filters.</div>`;
  document.querySelectorAll("[data-weather-location]").forEach(button => {
    button.addEventListener("click", () => {
      const row = state.coastalWeatherRows.find(item => item.location_id === button.dataset.weatherLocation);
      if (row) showCoastalWeatherCard(row);
    });
  });
}

function showCoastalWeatherCard(row) {
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card");
  card.classList.add("weather-detail-card");
  const warningReason = weatherWarningReason(row);
  const severity = warningReason ? "Warning" : "Normal";
  const sourceLink = row.source_url
    ? `<a class="official-port-link weather-source-link" href="${escapeAttr(row.source_url)}" target="_blank" rel="noopener">Open official ${escapeHtml(row.provider || "weather")} source</a>`
    : "";
  const details = weatherDetailEntries(row);
  const summary = row.location_type === "storm" ? null : row.weather_description || row.summary;
  const portAlert = portWeatherAlertReason(row);
  const cycloneMotion = row.location_type === "storm"
    ? `<div class="cyclone-card-motion cyclone-card-motion-large" aria-label="Forecast movement ${escapeAttr(row.movement_direction || "unknown")}"><span>🌀</span><i></i><b>➤</b><small>Forecast movement: ${escapeHtml(row.movement_direction || "not published")}</small></div>`
    : "";
  const sourceCaveat = row.location_type === "storm"
    ? ` GDACS aggregates the originating ${escapeHtml(row.source_agency || "RSMC / TCWC")} advisory. Affected ports are HRP proximity estimates and do not mean a port is closed. ${escapeHtml(row.forecast_disclaimer || "Track and landfall can change with each advisory.")}`
    : row.provider_code === "bmkg"
      ? " BMKG documents the current field as cm/s but its port pages also present currents in knots; visibility has no declared API unit. Those values are shown without inferred conversion."
      : " Port values mapped from a marine area are labelled as area-based forecasts, not port observations.";
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">${escapeHtml(row.provider || "Official")} ${escapeHtml(row.location_type === "storm" ? "tropical-cyclone alert" : row.location_type === "port" ? "port forecast" : "marine-area forecast")}</span>` +
    `<h2>${escapeHtml(coastalPortDisplayName(row))}</h2>` +
    `<p class="detail-meta">${escapeHtml(weatherPeriod(row))}</p>` +
    (portAlert ? `<div class="weather-port-alert-banner"><strong>Adverse weather</strong><span>${escapeHtml(portAlert)}</span></div>` : "") +
    `<div class="weather-card-severity severity-${warningReason ? "warning" : "normal"}">${escapeHtml(row.location_type === "storm" ? `${row.alert_level || "Active"} GDACS alert` : row.weather_risk_level ? `${row.weather_risk_level} port risk` : severity)}</div>` +
    (warningReason && !portAlert ? `<p class="weather-card-warning-copy">${escapeHtml(warningReason)}</p>` : "") +
    cycloneMotion +
    `<div class="detail-grid weather-detail-grid">${details.map(item => detailCell(item.label, item.value)).join("")}</div>` +
    (summary ? `<p class="weather-card-summary">${escapeHtml(summary)}</p>` : "") +
    sourceLink +
    `<p class="detail-note">Official forecast, not a live observation and not for navigation. Source: ${escapeHtml(row.provider || "official meteorological agency")}.${sourceCaveat}${row.risk_methodology ? ` Risk: ${escapeHtml(row.risk_methodology)}.` : ""}</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

function renderCoastalWeather() {
  if (!state.weatherLayer || !state.weatherSymbolLayer) return;
  state.weatherLayer.clearLayers();
  state.weatherSymbolLayer.clearLayers();
  if (!state.coastalWeatherEnabled) return;
  const rows = weatherVisibleRows();
  const mapZoom = state.map.getZoom();
  const symbolCells = new Set();
  rows.forEach(row => {
    const color = row.location_type === "port" ? "#2c91b4" : weatherColor(row.severity);
    const darkMap = state.mapSkin === "dark" || state.mapSkin === "satellite";
    const polygonStroke = darkMap ? "#f2f5f6" : "#17232b";
    const openWeatherDetails = event => {
      if (event?.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
      showCoastalWeatherCard(row);
    };
    if (row.location_type === "storm") {
      const alertColor = row.alert_level === "Red" ? "#b4141f" : row.alert_level === "Orange" ? "#e56a1b" : "#f0b429";
      const observedTrack = Array.isArray(row.observed_track) ? row.observed_track : [];
      const forecastTrack = Array.isArray(row.forecast_track) ? row.forecast_track : [];
      if (observedTrack.length > 1) {
        L.polyline(observedTrack, { color: "#536779", weight: 2, opacity: 0.8, className: "cyclone-observed-track" }).addTo(state.weatherLayer);
      }
      if (forecastTrack.length > 1) {
        const forecastLine = L.polyline(forecastTrack, {
          color: alertColor, weight: 3, opacity: 0.95, dashArray: "10 8",
          className: state.coastalWeatherAnimated ? "cyclone-forecast-track animated" : "cyclone-forecast-track"
        }).bindTooltip(`<strong>${escapeHtml(row.location_name)}</strong><br>Forecast movement: ${escapeHtml(row.movement_direction || "not published")}<br>Click for ports and landfall context`, { sticky: true, className: "weather-leaflet-tooltip" });
        forecastLine.on("click", openWeatherDetails);
        forecastLine.addTo(state.weatherLayer);
      }
      if (row.forecast_cone) {
        const cone = L.geoJSON(row.forecast_cone, { interactive: true, style: {
          color: alertColor, weight: 1.2, opacity: 0.8, fillColor: alertColor, fillOpacity: 0.07, dashArray: "5 4"
        }});
        cone.on("click", openWeatherDetails);
        cone.eachLayer(layer => layer.on("click", openWeatherDetails));
        cone.addTo(state.weatherLayer);
      }
      (row.affected_ports || []).slice(0, mapZoom >= 5 ? 30 : 12).forEach(port => {
        const portMarker = L.circleMarker([Number(port.latitude), Number(port.longitude)], {
          radius: mapZoom >= 6 ? 4 : 2.7, color: "#fff", weight: 1,
          fillColor: "#8a3ffc", fillOpacity: 0.92
        }).bindTooltip(`<strong>${escapeHtml(port.port_name)}</strong><br>${escapeHtml(port.country || "")}${port.country ? " · " : ""}${Number(port.distance_to_forecast_track_km).toLocaleString()} km from forecast track<br>Proximity estimate; not a closure notice`, { className: "weather-leaflet-tooltip" });
        portMarker.on("click", openWeatherDetails);
        portMarker.addTo(state.weatherLayer);
      });
      const stormMarker = L.marker([Number(row.latitude), Number(row.longitude)], {
        interactive: true, keyboard: true, title: `Open ${row.location_name} cyclone details`,
        icon: L.divIcon({
          className: "weather-symbol-marker cyclone-map-marker",
          html: `<span class="weather-cyclone${state.coastalWeatherAnimated ? " animated" : ""} alert-${escapeAttr(String(row.alert_level || "green").toLowerCase())}">🌀</span><b>${escapeHtml(String(row.storm_name || row.location_name).replace(/^(Tropical Cyclone|Cyclone)\s+/i, ""))}</b>`,
          iconSize: [92, 42], iconAnchor: [21, 21]
        })
      }).bindTooltip(`<strong>${escapeHtml(row.location_name)}</strong><br>${escapeHtml(row.weather_condition || "Tropical cyclone")}<br>${Number(row.max_wind_kn || 0).toLocaleString()} kt · moving ${escapeHtml(row.movement_direction || "unknown")}`, { className: "weather-leaflet-tooltip" });
      stormMarker.on("click", openWeatherDetails);
      stormMarker.addTo(state.weatherSymbolLayer);
      return;
    }
    let center = null;
    if (row.geometry) {
      const polygon = L.geoJSON(row.geometry, {
      interactive: state.coastalWeatherPolygonsVisible,
      style: {
        color: polygonStroke,
        weight: row.severity === "warning" ? 1.35 : 0.9,
        opacity: darkMap ? 0.9 : 0.82,
        fill: false,
        fillOpacity: 0,
        dashArray: row.severity === "normal" ? "4 3" : null
      }
      });
      center = polygon.getBounds().getCenter();
      if (state.coastalWeatherPolygonsVisible) {
        polygon.bindTooltip(coastalWeatherTooltip(row), {
          sticky: true,
          direction: "top",
          className: "weather-leaflet-tooltip",
          opacity: 1
        });
        polygon.on("click", openWeatherDetails);
        polygon.eachLayer(layer => layer.on("click", openWeatherDetails));
        polygon.addTo(state.weatherLayer);
      }
    } else if (row.latitude != null && row.longitude != null) {
      center = L.latLng(Number(row.latitude), Number(row.longitude));
      const marker = L.circleMarker(center, {
        radius: row.location_type === "port" ? (mapZoom >= 7 ? 6 : 5) : (mapZoom >= 7 ? 5 : 3.5),
        color: "#ffffff",
        weight: row.location_type === "port" ? 1.5 : 1,
        fillColor: color,
        fillOpacity: 0.95,
        interactive: true
      }).bindTooltip(coastalWeatherTooltip(row), {
        sticky: true,
        direction: "top",
        className: "weather-leaflet-tooltip",
        opacity: 1
      });
      marker.on("click", openWeatherDetails);
      marker.addTo(state.weatherLayer);
      if (row.location_type === "port") {
        const hitTarget = L.circleMarker(center, {
          radius: mapZoom >= 7 ? 14 : 11,
          stroke: false,
          fill: true,
          fillColor: "#2c91b4",
          fillOpacity: 0.001,
          interactive: true,
          bubblingMouseEvents: false
        });
        hitTarget.on("click", openWeatherDetails);
        hitTarget.addTo(state.weatherLayer);
      }
    }
    if (!center) return;
    const portAlert = state.coastalWeatherParameters.has("warning")
      ? portWeatherAlertReason(row)
      : "";
    if (row.location_type === "port" && !portAlert && !weatherPortVisibleAtZoom(row, mapZoom)) return;
    if (
      row.location_type === "water" && row.provider_code === "bmkg" &&
      mapZoom <= 5 && !weatherSignalIsNoteworthy(row)
    ) return;
    if (row.location_type === "water" && row.provider_code === "bmkg" && mapZoom < 8) {
      const cellSize = mapZoom <= 5 ? 8 : mapZoom === 6 ? 5 : 3;
      const cell = `${Math.round(center.lat / cellSize)}:${Math.round(center.lng / cellSize)}`;
      if (symbolCells.has(cell)) return;
      symbolCells.add(cell);
    }
    const symbolHtml = weatherSymbolHtml(row);
    if (!symbolHtml) return;
    const weatherMarker = L.marker(center, {
      interactive: true,
      keyboard: true,
      title: `Open ${coastalPortDisplayName(row)} weather report`,
      icon: L.divIcon({
        className: "weather-symbol-marker",
        html: symbolHtml,
        iconSize: [34, 34],
        iconAnchor: [17, 17]
      })
    });
    weatherMarker.on("click", openWeatherDetails);
    weatherMarker.addTo(state.weatherSymbolLayer);
  });
  document.getElementById("weather-layer-count").textContent =
    rows.length ? (rows.every(row => row.location_type === "storm") ? `${rows.length} active storms` : `${rows.length} forecasts`) : "No values";
}

function loadAisPreferences() {
  try {
    const mode = window.localStorage.getItem("hrp-ais-display-mode");
    state.aisDisplayMode = mode === "selected" ? "selected" : "all";
    const typeFilter = window.localStorage.getItem("hrp-ais-type-filter");
    state.aisTypeFilter = new Set(["cargo_tanker", "cargo", "tanker", "all"])
      .has(typeFilter)
      ? typeFilter
      : "cargo_tanker";
    const allowedRegions = new Set(["current", ...Object.keys(AIS_REGION_BOUNDS)]);
    const savedRegions = JSON.parse(
      window.localStorage.getItem("hrp-ais-regions") || "null"
    );
    const regions = Array.isArray(savedRegions)
      ? savedRegions.filter(region => allowedRegions.has(region))
      : DEFAULT_AIS_REGIONS;
    state.aisRegions = new Set(regions.length ? regions : DEFAULT_AIS_REGIONS);
    if (state.aisRegions.has("world")) state.aisRegions = new Set(["world"]);
    const saved = JSON.parse(
      window.localStorage.getItem("hrp-ais-watchlist") || "[]"
    );
    state.aisWatchlist = new Map(
      (Array.isArray(saved) ? saved : [])
        .filter(vessel => /^\d{9}$/.test(String(vessel.mmsi || "")))
        .slice(0, 50)
        .map(vessel => [String(vessel.mmsi), vessel])
    );
  } catch {
    state.aisDisplayMode = "all";
    state.aisTypeFilter = "cargo_tanker";
    state.aisRegions = new Set(DEFAULT_AIS_REGIONS);
    state.aisWatchlist = new Map();
  }
  document.getElementById("ais-display-mode").value = state.aisDisplayMode;
  document.getElementById("ais-type-filter").value = state.aisTypeFilter;
  document.querySelectorAll("#ais-region-options input").forEach(input => {
    input.checked = state.aisRegions.has(input.value);
  });
  updateAisRegionSummary();
  renderAisWatchlist();
}

function saveAisPreferences() {
  try {
    window.localStorage.setItem("hrp-ais-display-mode", state.aisDisplayMode);
    window.localStorage.setItem("hrp-ais-type-filter", state.aisTypeFilter);
    window.localStorage.setItem(
      "hrp-ais-regions",
      JSON.stringify(Array.from(state.aisRegions))
    );
    window.localStorage.setItem(
      "hrp-ais-watchlist",
      JSON.stringify(Array.from(state.aisWatchlist.values()))
    );
  } catch {
    // Browser storage can be unavailable in privacy-restricted sessions.
  }
}

function updateAisRegionSummary() {
  const summary = document.getElementById("ais-region-summary");
  if (!summary) return;
  if (state.aisRegions.has("world")) {
    summary.textContent = "Worldwide";
  } else if (state.aisRegions.size === 1 && state.aisRegions.has("current")) {
    summary.textContent = "Current map";
  } else {
    summary.textContent = `${state.aisRegions.size} selected`;
  }
}

function aisVesselInSelectedRegions(vessel) {
  if (state.aisRegions.has("world")) return true;
  const lat = Number(vessel.lat);
  const lon = Number(vessel.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (
    state.aisRegions.has("current")
    && state.map?.getBounds().contains([lat, lon])
  ) {
    return true;
  }
  return Array.from(state.aisRegions).some(region => {
    const bounds = AIS_REGION_BOUNDS[region];
    if (!bounds) return false;
    return (
      lat >= bounds[0][0] && lat <= bounds[1][0]
      && lon >= bounds[0][1] && lon <= bounds[1][1]
    );
  });
}

function addAisWatchlistVessels(vessels) {
  vessels.slice(0, 50).forEach(vessel => {
    const mmsi = String(vessel.mmsi || "");
    if (!/^\d{9}$/.test(mmsi)) return;
    state.aisWatchlist.set(mmsi, {
      mmsi,
      imo: vessel.imo || "",
      name: vessel.name || `MMSI ${mmsi}`
    });
  });
  while (state.aisWatchlist.size > 50) {
    const oldest = state.aisWatchlist.keys().next().value;
    state.aisWatchlist.delete(oldest);
  }
  saveAisPreferences();
  renderAisWatchlist();
}

function removeAisWatchlistVessel(mmsi) {
  state.aisWatchlist.delete(String(mmsi));
  saveAisPreferences();
  renderAisWatchlist();
  renderAisVessels();
  if (state.aisEnabled && state.aisDisplayMode === "selected") {
    refreshAisLayer();
  }
}

function renderAisWatchlist() {
  const container = document.getElementById("ais-watchlist");
  if (!state.aisWatchlist.size) {
    container.innerHTML = "<span>No selected vessels.</span>";
    return;
  }
  container.innerHTML = Array.from(state.aisWatchlist.values())
    .map(vessel => `
      <button type="button" data-ais-remove="${escapeAttr(vessel.mmsi)}"
        title="Remove ${escapeAttr(vessel.name)}">
        <strong>${escapeHtml(vessel.name)}</strong>
        <small>${escapeHtml(vessel.mmsi)}</small>
        <i aria-hidden="true">×</i>
      </button>
    `)
    .join("");
  container.querySelectorAll("[data-ais-remove]").forEach(button => {
    button.addEventListener("click", () => {
      removeAisWatchlistVessel(button.dataset.aisRemove);
    });
  });
}

function displayedAisVessels() {
  return state.aisVessels.filter(vessel => {
    if (
      state.aisDisplayMode === "selected"
      && !state.aisWatchlist.has(String(vessel.mmsi || ""))
    ) {
      return false;
    }
    if (
      state.aisDisplayMode !== "selected"
      && !aisVesselInSelectedRegions(vessel)
    ) {
      return false;
    }
    const category = aisVesselTypeCategory(vessel.ship_type);
    if (state.aisTypeFilter === "all") return true;
    if (state.aisTypeFilter === "cargo") return category === "cargo";
    if (state.aisTypeFilter === "tanker") return category === "tanker";
    return category === "cargo" || category === "tanker" || category === "unknown";
  });
}

function aisVesselTypeCategory(value) {
  const type = Number(value);
  if (!Number.isFinite(type)) return "unknown";
  if (type >= 70 && type <= 79) return "cargo";
  if (type >= 80 && type <= 89) return "tanker";
  if (type >= 60 && type <= 69) return "passenger";
  if (type >= 40 && type <= 49) return "high_speed";
  if (type === 30) return "fishing";
  if ([31, 32, 52].includes(type)) return "tug_tow";
  if ([36, 37].includes(type)) return "pleasure";
  if (type >= 33 && type <= 59) return "special";
  if (type >= 90 && type <= 99) return "other";
  return "unknown";
}

function aisVesselTypeLabel(value) {
  const labels = {
    cargo: "Cargo vessel",
    tanker: "Tanker",
    passenger: "Passenger vessel",
    high_speed: "High-speed craft",
    fishing: "Fishing vessel",
    tug_tow: "Tug / towing vessel",
    pleasure: "Sailing / pleasure craft",
    special: "Special-purpose vessel",
    other: "Other vessel",
    unknown: "Type not yet received"
  };
  return labels[aisVesselTypeCategory(value)];
}

function setAisStatus(text, kind = "") {
  const element = document.getElementById("ais-status");
  element.textContent = text;
  element.dataset.kind = kind;
}

async function setAisEnabled(enabled) {
  state.aisEnabled = Boolean(enabled);
  window.clearInterval(state.aisRefreshTimer);
  state.aisRefreshTimer = null;
  if (!state.aisEnabled) {
    clearAisVessels(false);
    document.getElementById("ais-layer-count").textContent = "Off";
    setAisStatus("AIS layer is switched off.");
    updateMapStatus();
    return;
  }
  try {
    const response = await fetch("/api/ais/status");
    const status = await response.json();
    if (!status.configured) {
      document.getElementById("ais-enabled").checked = false;
      state.aisEnabled = false;
      document.getElementById("ais-layer-count").textContent = "Setup";
      setAisStatus(
        "Add AISSTREAM_API_KEY to the server environment, then restart the app.",
        "error"
      );
      return;
    }
    setAisStatus("Connecting to live AIS observations…", "loading");
    await refreshAisLayer();
    if (state.aisEnabled) {
      state.aisRefreshTimer = window.setInterval(() => refreshAisLayer(), 10_000);
    }
  } catch (error) {
    setAisStatus(error.message || "AIS status could not be checked.", "error");
  }
}

function clearAisVessels(showMessage = true) {
  state.aisLayer.clearLayers();
  state.aisTrailLayer.clearLayers();
  state.aisVessels = [];
  state.selectedAisMmsi = null;
  if (state.aisEnabled) {
    document.getElementById("ais-layer-count").textContent = "0 retained";
    if (showMessage) {
      setAisStatus("Retained vessels cleared. Press Refresh to receive the current map area.");
    }
  }
  updateMapStatus();
}

function currentAisBounds() {
  const bounds = state.map.getBounds();
  return {
    south: Math.max(-90, bounds.getSouth()),
    north: Math.min(90, bounds.getNorth()),
    west: Math.max(-180, bounds.getWest()),
    east: Math.min(180, bounds.getEast())
  };
}

async function refreshAisLayer(isSearch = false) {
  if (!state.aisEnabled || state.aisLoading) return;
  const selectedMmsis = state.aisDisplayMode === "selected" && !isSearch
    ? Array.from(state.aisWatchlist.keys())
    : [];
  if (
    state.aisDisplayMode === "selected"
    && !isSearch
    && !selectedMmsis.length
  ) {
    setAisStatus("Add at least one vessel to use Selected vessels only.", "warning");
    renderAisVessels();
    return;
  }
  state.aisLoading = true;
  const query = document.getElementById("ais-search").value.trim();
  const searchButton = document.getElementById("ais-search-button");
  const refreshButton = document.getElementById("ais-refresh");
  const clearButton = document.getElementById("ais-clear");
  searchButton.disabled = true;
  refreshButton.disabled = true;
  clearButton.disabled = true;
  setAisStatus(
    query && isSearch ? `Searching for “${query}”…` : "Receiving live AIS positions…",
    "loading"
  );
  try {
    const response = await fetch("/api/ais/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...currentAisBounds(),
        query: query && isSearch ? query : null,
        mmsis: selectedMmsis,
        regions: Array.from(state.aisRegions),
        timeout_sec: 2,
        max_vessels: 1000
      })
    });
    const json = await response.json();
    if (!response.ok) {
      throw new Error(json.detail || "AIS feed request failed.");
    }
    const received = json.vessels || [];
    const retained = new Map(
      state.aisVessels.map(vessel => [String(vessel.mmsi || vessel.imo), vessel])
    );
    let added = 0;
    received.forEach(vessel => {
      const key = String(vessel.mmsi || vessel.imo || "");
      if (!key) return;
      if (!retained.has(key)) added += 1;
      retained.set(key, { ...(retained.get(key) || {}), ...vessel });
    });
    state.aisVessels = Array.from(retained.values());
    if (isSearch && received.length) {
      addAisWatchlistVessels(received);
    }
    renderAisVessels();
    const receivedCount = received.length;
    const retainedCount = state.aisVessels.length;
    const sampled = json.sampled_at
      ? new Date(json.sampled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "now";
    const shownCount = displayedAisVessels().length;
    document.getElementById("ais-layer-count").textContent =
      state.aisDisplayMode === "selected"
        ? `${shownCount} selected`
        : `${shownCount} shown`;
    if (query && isSearch && !receivedCount) {
      setAisStatus(
        `No current AIS match for “${query}” in this sample. Name and IMO searches depend on static AIS messages.`,
        "warning"
      );
    } else {
      const updateText = added
        ? `${added.toLocaleString()} new, ${Math.max(0, receivedCount - added).toLocaleString()} updated`
        : `${receivedCount.toLocaleString()} updated`;
      setAisStatus(
        `${updateText} at ${sampled}. ${shownCount.toLocaleString()} shown; ${retainedCount.toLocaleString()} retained.`
      );
    }
  } catch (error) {
    setAisStatus(error.message || "AIS positions could not be loaded.", "error");
  } finally {
    state.aisLoading = false;
    searchButton.disabled = false;
    refreshButton.disabled = false;
    clearButton.disabled = false;
  }
}

function aisObservationAgeClass(vessel) {
  const observed = Date.parse(vessel.last_update || "");
  if (!Number.isFinite(observed)) return "ais-age-unknown";
  const ageMinutes = Math.max(0, (Date.now() - observed) / 60_000);
  if (ageMinutes <= 15) return "ais-age-fresh";
  if (ageMinutes <= 60) return "ais-age-aging";
  return "ais-age-stale";
}

function formatAisObservedAt(vessel) {
  const observed = Date.parse(vessel.last_update || "");
  if (!Number.isFinite(observed)) return "time unavailable";
  return new Date(observed).toLocaleString([], {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function renderAisVessels() {
  state.aisLayer.clearLayers();
  const displayed = displayedAisVessels();
  displayed.forEach(vessel => {
    const lat = Number(vessel.lat);
    const lon = Number(vessel.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const course = Number(vessel.cog ?? vessel.heading ?? 0);
    const moving = Number(vessel.sog_kn || 0) >= 0.5;
    const marker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: `ais-vessel-icon ${aisObservationAgeClass(vessel)}`,
        html: `<span class="${moving ? "moving" : "stationary"}" style="--ais-course:${Number.isFinite(course) ? course : 0}deg"></span>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10]
      }),
      zIndexOffset: 650
    });
    const name = vessel.name || `MMSI ${vessel.mmsi}`;
    marker.bindTooltip(
      `<strong>${escapeHtml(name)}</strong><br>${formatAisMotion(vessel)}<br><small>Last received ${escapeHtml(formatAisObservedAt(vessel))}</small>`,
      { className: "asset-tooltip ais-tooltip", direction: "top", opacity: 1 }
    );
    marker.on("click", () => showAisVessel(vessel, marker));
    marker.addTo(state.aisLayer);
  });
  document.getElementById("ais-layer-count").textContent = state.aisEnabled
    ? state.aisDisplayMode === "selected"
      ? `${displayed.length} selected`
      : `${displayed.length} shown`
    : "Off";
  updateMapStatus();
}

function formatAisMotion(vessel) {
  const facts = [aisVesselTypeLabel(vessel.ship_type)];
  if (vessel.sog_kn != null) facts.push(`${formatNumber(vessel.sog_kn, 1)} kn`);
  if (vessel.cog != null) facts.push(`COG ${formatNumber(vessel.cog, 0)}°`);
  if (vessel.destination) facts.push(`To ${vessel.destination}`);
  return facts.join(" · ") || "Position received";
}

function aisPopupHtml(vessel, trailCount = null) {
  const name = vessel.name || "Unnamed AIS target";
  const fields = [
    ["MMSI", vessel.mmsi],
    ["IMO", vessel.imo],
    ["Vessel type", aisVesselTypeLabel(vessel.ship_type)],
    ["Call sign", vessel.call_sign],
    ["Speed", vessel.sog_kn == null ? null : `${formatNumber(vessel.sog_kn, 1)} kn`],
    ["Course", vessel.cog == null ? null : `${formatNumber(vessel.cog, 0)}°`],
    ["Heading", vessel.heading == null ? null : `${formatNumber(vessel.heading, 0)}°`],
    ["Destination", vessel.destination],
    ["ETA", vessel.eta],
    ["Last AIS", vessel.last_update],
    ["Recorded trail", trailCount == null ? "Loading…" : `${trailCount} positions`]
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return `
    <div class="ais-popup">
      <span class="ais-popup-kicker">LIVE AIS TARGET</span>
      <h3>${escapeHtml(name)}</h3>
      <div class="ais-popup-grid">
        ${fields.map(([label, value]) => `
          <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
        `).join("")}
      </div>
      <small>Trail contains actual observations retained by this dashboard, not a predicted voyage.</small>
    </div>
  `;
}

async function showAisVessel(vessel, marker) {
  state.selectedAisMmsi = vessel.mmsi;
  state.aisTrailLayer.clearLayers();
  marker.bindPopup(aisPopupHtml(vessel), {
    className: "ais-vessel-popup",
    minWidth: 290,
    maxWidth: 360
  }).openPopup();
  try {
    const response = await fetch(`/api/ais/trail/${encodeURIComponent(vessel.mmsi)}?hours=2160&limit=3000`);
    const json = await response.json();
    if (!response.ok) throw new Error(json.detail || "Trail unavailable");
    if (state.selectedAisMmsi !== vessel.mmsi) return;
    const points = (json.points || [])
      .map(point => [Number(point.lat), Number(point.lon)])
      .filter(([lat, lon]) => Number.isFinite(lat) && Number.isFinite(lon));
    if (points.length >= 2) {
      L.polyline(points, {
        color: "#008ea8",
        weight: 3,
        opacity: 0.88,
        dashArray: null,
        lineJoin: "round"
      }).addTo(state.aisTrailLayer);
      L.circleMarker(points[0], {
        radius: 3,
        color: "#ffffff",
        weight: 1,
        fillColor: "#008ea8",
        fillOpacity: 1
      }).bindTooltip("First recorded AIS position").addTo(state.aisTrailLayer);
    }
    marker.setPopupContent(aisPopupHtml(vessel, points.length));
  } catch (error) {
    marker.setPopupContent(aisPopupHtml(vessel, 0));
  }
}

function setMapSkin(skin) {
  if (!MAP_SKINS[skin]) skin = "light";
  if (state.baseLayer && state.map.hasLayer(state.baseLayer)) {
    state.map.removeLayer(state.baseLayer);
  }
  state.mapSkin = skin;
  state.baseLayer = MAP_SKINS[skin]();
  state.baseLayer.addTo(state.map);
  state.baseLayer.bringToBack?.();
  document.getElementById("map")?.setAttribute("data-map-skin", skin);
  const selector = document.getElementById("map-skin");
  if (selector) selector.value = skin;
  if (state.coastalWeatherEnabled) renderCoastalWeather();
}

function addEnglishMapLabels() {
  const makeLabel = (item, kind) => {
    const [text, lat, lon] = item;
    const width = kind === "continents"
      ? 150
      : COUNTRY_LABEL_WIDTHS[text] || 70;
    return L.marker(
    [lat, lon],
    {
      interactive: false,
      icon: L.divIcon({
        className: `english-map-label ${kind === "continents" ? "continent-label" : "country-label"}`,
        html: `<span style="--country-label-width:${width}px">${escapeHtml(text)}</span>`,
        iconSize: [width, 28],
        iconAnchor: [width / 2, 14]
      })
    }
  )};
  state.continentLabels = L.layerGroup(
    ENGLISH_MAP_LABELS.continents.map(item => makeLabel(item, "continents"))
  ).addTo(state.map);
  state.countryLabels = L.layerGroup(
    ENGLISH_MAP_LABELS.countries.map(item => makeLabel(item, "countries"))
  );
  const refresh = () => {
    const zoom = state.map.getZoom();
    document.getElementById("map").dataset.labelZoom =
      zoom >= 7 ? "detail" : zoom >= 5 ? "regional" : "world";
    if (zoom <= 3) {
      if (!state.map.hasLayer(state.continentLabels)) state.continentLabels.addTo(state.map);
      if (state.map.hasLayer(state.countryLabels)) state.map.removeLayer(state.countryLabels);
    } else {
      if (state.map.hasLayer(state.continentLabels)) state.map.removeLayer(state.continentLabels);
      if (!state.map.hasLayer(state.countryLabels)) state.countryLabels.addTo(state.map);
    }
  };
  state.map.on("zoomend", refresh);
  refresh();
}

function portsAllowedForMode() {
  if (state.routeMode) return true;
  if (state.mode === "ports") return document.getElementById("show-ports").checked;
  if (state.mode === "energy") return document.getElementById("energy-show-ports").checked;
  if (state.mode === "commodities") return document.getElementById("commodity-show-ports").checked;
  return false;
}

async function loadPortFacets() {
  const response = await fetch("/api/ports/facets");
  const json = await response.json();
  const facets = json.facets || {};
  populateSelect("port-country", "All countries", facets.countries || []);
  populateSelect("port-size", "All sizes", facets.harbor_sizes || []);
  const counts = Object.fromEntries((facets.categories || []).map(item => [item.id, item.count]));
  ["dry_bulk", "coal"].forEach(key => {
    const el = document.getElementById("count-" + key.replaceAll("_", "-"));
    const label = document.querySelector(`[data-category="${key}"]`);
    const count = Number(counts[key] || 0);
    if (el) el.textContent = count.toLocaleString();
    if (label) label.hidden = count <= 0;
  });
}

async function loadWorkspaceFacets() {
  await Promise.all(Object.entries(WORKSPACE_LAYERS).map(async ([mode, layers]) => {
    const response = await fetch("/api/layer-facets?trackers=" + layers.join(","));
    if (!response.ok) return;
    const facets = await response.json();
    populateSelect(`${mode === "energy" ? "energy" : "commodity"}-country`, "All countries", facets.countries || []);
  }));
}

async function loadCoalWorkspace() {
  try {
    const statusGroup = document.getElementById("coal-asset-status").value;
    const [summaryResponse, assetsResponse] = await Promise.all([
      fetch("/api/coal/summary"),
      fetch(`/api/coal/assets?status_group=${encodeURIComponent(statusGroup)}&limit=20000`)
    ]);
    if (!summaryResponse.ok || !assetsResponse.ok) throw new Error("Coal workspace data could not be loaded");
    state.coalSummary = await summaryResponse.json();
    const assetPayload = await assetsResponse.json();
    state.coalAssets = assetPayload.data || [];
    const counts = {};
    state.coalAssets.forEach(item => {
      counts[item.asset_kind] = (counts[item.asset_kind] || 0) + 1;
    });
    document.getElementById("coal-mine-count").textContent = Number(counts.coal_mines || 0).toLocaleString();
    document.getElementById("coal-terminal-count").textContent = Number(counts.coal_trade_terminals || 0).toLocaleString();
    document.getElementById("coal-port-count").textContent = Number(counts.dry_bulk_ports || 0).toLocaleString();
    document.getElementById("coal-power-count").textContent = Number(counts.power_consumers || 0).toLocaleString();
    document.getElementById("coal-steel-count").textContent = Number(counts.steel_consumers || 0).toLocaleString();
    document.getElementById("coal-cement-count").textContent = Number(counts.cement_consumers || 0).toLocaleString();
    const hasDatasets = (state.coalSummary.datasets || []).length > 0;
    document.getElementById("coal-data-status").textContent = hasDatasets
      ? `${state.coalSummary.datasets.length} dataset${state.coalSummary.datasets.length === 1 ? "" : "s"}`
      : "India workspace";
    document.getElementById("coal-header-status").textContent = hasDatasets
      ? `${state.coalSummary.datasets.length} uploaded dataset${state.coalSummary.datasets.length === 1 ? "" : "s"}`
      : coalMasterHeader(state.coalSummary.official_master);
    await loadCoalAnalysis();
    refreshCoalActionState();
    if (hasDatasets) {
      document.getElementById("coal-upload-message").textContent =
        "Uploaded data is stored separately from GEM/WPI map context. Review its detected date and numeric fields before analysis.";
    } else {
      document.getElementById("coal-upload-message").textContent =
        "Official Coal Directory annual series is loaded. Uploads remain optional for monthly, weekly, plant-level or driver analysis.";
    }
    renderCoalAssetViews();
    renderCoalLayers();
  } catch (error) {
    document.getElementById("coal-upload-message").textContent = error.message;
  }
}

function coalMasterHeader(master) {
  if (!master || !Number(master.normalized_row_count || 0)) {
    return "Awaiting operational data";
  }
  return `${Number(master.normalized_row_count || 0).toLocaleString()} official rows`;
}

async function loadCoalAnalysis() {
  const from = document.getElementById("coal-analysis-from");
  const to = document.getElementById("coal-analysis-to");
  if (!from.options.length) {
    const periods = [];
    for (let date = new Date(2023, 4, 1); date <= new Date(2026, 5, 1); date.setMonth(date.getMonth() + 1)) {
      periods.push(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`);
    }
    from.innerHTML = periods.map(period =>
      `<option value="${escapeAttr(period)}">${escapeHtml(formatCoalPeriod(period))}</option>`
    ).join("");
    to.innerHTML = from.innerHTML;
    from.value = periods[0];
    to.value = periods[periods.length - 1];
  }
  await loadCoalDashboard();
}

function formatCoalPeriod(period) {
  return formatMonthYear(period);
}

async function setCoalDashboardTab(tab) {
  state.coalDashboardTab = tab;
  document.querySelectorAll("[data-coal-dashboard-tab]").forEach(button => {
    button.classList.toggle("active", button.dataset.coalDashboardTab === tab);
  });
  await loadCoalDashboard();
}

function applyCoalRangePreset(preset) {
  const from = document.getElementById("coal-analysis-from");
  const to = document.getElementById("coal-analysis-to");
  const periods = Array.from(from.options).map(option => option.value);
  if (!periods.length) return;
  const counts = { "12m": 12, "24m": 24, "3y": 36 };
  const count = counts[preset] || periods.length;
  from.value = periods[Math.max(0, periods.length - count)];
  to.value = periods[periods.length - 1];
  document.querySelectorAll("[data-coal-range]").forEach(button => {
    button.classList.toggle("active", button.dataset.coalRange === preset);
  });
  loadCoalDashboard();
}

async function loadCoalDashboard() {
  const container = document.getElementById("coal-dashboard-panels");
  const start = document.getElementById("coal-analysis-from").value || "2023-05";
  const end = document.getElementById("coal-analysis-to").value || "2026-06";
  const frequency = document.getElementById("coal-analysis-frequency").value || "monthly";
  const focus = document.getElementById("coal-analysis-focus").value || "all";
  const comparison = document.getElementById("coal-analysis-comparison").value || "previous_period";
  if (start > end) {
    container.innerHTML = `<div class="coal-dashboard-error">The From month must be before the To month.</div>`;
    return;
  }
  container.innerHTML = `<div class="coal-dashboard-loading">Loading official ${escapeHtml(state.coalDashboardTab)} data…</div>`;
  const params = new URLSearchParams({ tab: state.coalDashboardTab, start, end, frequency, focus, comparison });
  try {
    const response = await fetch(`/api/coal/dashboard?${params}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Coal dashboard data is unavailable");
    state.coalAnalysis = payload;
    const focusSelect = document.getElementById("coal-analysis-focus");
    focusSelect.innerHTML = (payload.focus_options || []).map(option =>
      `<option value="${escapeAttr(option.id)}">${escapeHtml(option.label)}</option>`
    ).join("");
    focusSelect.value = payload.focus || "all";
    renderCoalDashboard(payload);
    document.getElementById("coal-dashboard-csv").href = `/api/coal/dashboard/export?${params}&format=csv`;
    document.getElementById("coal-dashboard-xlsx").href = `/api/coal/dashboard/export?${params}&format=xlsx`;
    document.getElementById("coal-header-status").textContent =
      `${payload.rows.length} ${payload.frequency.replace("_", " ")} observations · official through ${payload.available_range.end}`;
  } catch (error) {
    container.innerHTML = `<div class="coal-dashboard-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderCoalDashboard(payload) {
  const availability = payload.available_range || {};
  const selectedOutside = payload.rows.length === 0;
  document.getElementById("coal-dashboard-availability").innerHTML =
    `<div><strong>${escapeHtml(payload.tab === "trade" ? "Trade data coverage" : "Official data coverage")}</strong>` +
    `<span>${escapeHtml(String(availability.start || "—"))} to ${escapeHtml(String(availability.end || "—"))} · ${escapeHtml(availability.grain || payload.frequency)} · ${escapeHtml(availability.status || "official")}</span></div>` +
    `${availability.limitation ? `<p>${escapeHtml(availability.limitation)}</p>` : ""}` +
    `${selectedOutside ? `<b>No verified rows fall inside the selected range. Filters were not silently ignored.</b>` : ""}`;
  renderCoalActiveFilters(payload);
  document.getElementById("coal-dashboard-kpis").innerHTML = (payload.kpis || []).map(kpi => {
    const numericValue = Number(kpi.value);
    const decimals = Number.isInteger(numericValue) || Math.abs(numericValue) >= 1000 ? 0 : 1;
    const display = kpi.display || (kpi.value === null || kpi.value === undefined ? "—" : formatNumber(kpi.value, decimals));
    const comparison = coalKpiComparison(kpi, payload);
    return `<article><span>${escapeHtml(kpi.label)}</span><strong>${escapeHtml(String(display))}${kpi.unit ? ` <small>${escapeHtml(kpi.unit)}</small>` : ""}</strong>` +
      `<p>${escapeHtml(kpi.detail || "")}</p>${comparison ? `<b class="coal-kpi-delta ${comparison.direction}">${escapeHtml(comparison.label)}</b>` : ""}</article>`;
  }).join("");

  const container = document.getElementById("coal-dashboard-panels");
  if (payload.tab === "table") {
    container.innerHTML = dashboardTable(payload, true);
    bindCoalTableSearch(container);
    return;
  }
  container.innerHTML = (payload.charts || []).map((chart, index) =>
    `<article class="coal-dashboard-card ${index === 0 ? "coal-dashboard-card-wide" : ""}">` +
    `<header><div><span>${escapeHtml(payload.tab.toUpperCase())}</span><h3>${escapeHtml(chart.title)}</h3><p>${escapeHtml(chart.subtitle || "")}</p></div>` +
    `<small>${escapeHtml(chart.y_label)}</small></header>` +
    `<div class="coal-dashboard-chart" id="coal-dynamic-chart-${index}"></div></article>`
  ).join("") + dashboardTable(payload, false) + dashboardSources(payload);
  (payload.charts || []).forEach((chart, index) => renderDynamicCoalChart(
    `coal-dynamic-chart-${index}`,
    Array.isArray(chart.rows) ? chart.rows : payload.rows,
    chart
  ));
  bindCoalTableSearch(container);
}

function renderCoalActiveFilters(payload) {
  const focus = (payload.focus_options || []).find(option => option.id === payload.focus)?.label || "All measures";
  const compareLabels = { previous_period: "vs previous period", previous_year: "vs previous year", none: "no comparison" };
  const chips = [
    labelize(payload.tab),
    `${formatCoalPeriod(payload.filters.from)} – ${formatCoalPeriod(payload.filters.to)}`,
    labelize(payload.frequency),
    focus,
    compareLabels[payload.comparison] || "no comparison"
  ];
  document.getElementById("coal-active-filters").innerHTML = chips.map((chip, index) =>
    `<span class="${index === 0 ? "primary" : ""}">${escapeHtml(chip)}</span>`
  ).join("");
}

function coalKpiComparison(kpi, payload) {
  if (payload.comparison === "none" || !payload.rows?.length) return null;
  const keyByLabel = {
    "Latest production": "production_mt", "Latest dispatch": "dispatch_mt",
    "Latest imports": "total_coal_mt", "Coking coal": "coking_coal_mt",
    "Non-coking coal": "non_coking_coal_mt", "FY2025-26 imports": "total_imports_mt",
    "Coal generation": "coal_generation_gwh", "Coal share of all generation": "coal_share_pct",
    "Renewables incl. large hydro": "renewables_share_pct", "Solar generation": "solar_generation_gwh",
    "Pit-head closing stock": "closing_stock_mt", "Annual off-take": "offtake_mt", "Annual production": "production_mt"
  };
  const key = keyByLabel[kpi.label];
  if (!key) return null;
  const values = payload.rows.map(row => Number(row[key])).filter(Number.isFinite);
  const lag = payload.comparison === "previous_year"
    ? (payload.frequency === "monthly" ? 12 : payload.frequency === "quarterly" ? 4 : 1)
    : 1;
  if (values.length <= lag) return null;
  const current = values[values.length - 1], prior = values[values.length - 1 - lag];
  if (!Number.isFinite(current) || !Number.isFinite(prior) || prior === 0) return null;
  const delta = (current / prior - 1) * 100;
  return { direction: delta > 0 ? "up" : delta < 0 ? "down" : "flat", label: `${delta >= 0 ? "+" : ""}${formatNumber(delta, 1)}% ${payload.comparison === "previous_year" ? "YoY" : "vs prior"}` };
}

function dashboardTable(payload, expanded) {
  const columns = payload.columns || [];
  const rows = payload.rows || [];
  return `<article class="coal-dashboard-card coal-dashboard-card-wide coal-dashboard-table-card ${expanded ? "expanded" : ""}">` +
    `<header><div><span>FILTERED DATA</span><h3>${expanded ? "Data explorer" : "Exact values behind this view"}</h3>` +
    `<p>${rows.length} rows · export uses this exact tab, range, focus and frequency</p></div>` +
    `<label class="coal-table-search"><span>Search rows</span><input type="search" placeholder="Filter visible records…" /></label></header>` +
    `<div class="coal-dashboard-table"><table><thead><tr>${columns.map(column => `<th>${escapeHtml(labelize(column))}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map(row => `<tr>${columns.map(column => `<td>${formatDashboardCell(row[column], column)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></article>`;
}

function bindCoalTableSearch(container) {
  container.querySelectorAll(".coal-table-search input").forEach(input => {
    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();
      const table = input.closest("article").querySelector("tbody");
      table.querySelectorAll("tr").forEach(row => {
        row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
      });
    });
  });
}

function dashboardSources(payload) {
  return `<article class="coal-dashboard-card coal-dashboard-card-wide coal-dashboard-sources"><header><div><span>LINEAGE &amp; QUALITY</span><h3>Official sources</h3></div></header>` +
    `<div>${(payload.sources || []).map(source => `<a href="${escapeAttr(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title)}</a>`).join("")}</div>` +
    `<p>${escapeHtml(payload.quality?.note || "")}</p></article>`;
}

function formatDashboardCell(value, column) {
  if (value === null || value === undefined || value === "") return "<span class=\"coal-null\">—</span>";
  if (typeof value === "number") return escapeHtml(formatNumber(value, column.includes("pct") ? 1 : 2));
  if (column.includes("url")) return `<a href="${escapeAttr(value)}" target="_blank" rel="noopener">Source</a>`;
  return escapeHtml(String(value));
}

function renderDynamicCoalChart(id, rows, chart) {
  const container = document.getElementById(id);
  const series = chart.series || [];
  const chartNumber = value => {
    if (value === null || value === undefined || value === "") return NaN;
    const result = Number(value);
    return Number.isFinite(result) ? result : NaN;
  };
  const validValues = rows.flatMap(row => series.map(item => chartNumber(row[item.key])).filter(Number.isFinite));
  if (!rows.length || !validValues.length) {
    container.innerHTML = `<div class="coal-dashboard-empty">No verified observations for these filters.</div>`;
    return;
  }
  const width = 780, height = 300, pad = { left: 66, right: 22, top: 28, bottom: 62 };
  const minValue = chart.y_label.includes("Change") ? Math.min(0, ...validValues) : 0;
  const stackedTotals = chart.type === "stacked_column"
    ? rows.map(row => series.reduce((sum, item) => {
        const value = chartNumber(row[item.key]);
        return sum + (Number.isFinite(value) ? Math.max(0, value) : 0);
      }, 0))
    : [];
  const maxValue = Math.max(...validValues, ...stackedTotals, 1);
  const span = Math.max(maxValue - minValue, 1);
  const x = index => pad.left + (rows.length === 1 ? 0.5 : index / (rows.length - 1)) * (width - pad.left - pad.right);
  const y = value => pad.top + (maxValue - Number(value)) / span * (height - pad.top - pad.bottom);
  const ticks = Array.from({ length: 5 }, (_, index) => minValue + span * index / 4);
  const grid = ticks.map(value => `<line x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}"></line><text x="${pad.left - 10}" y="${y(value) + 4}" text-anchor="end">${escapeHtml(formatNumber(value, 0))}</text>`).join("");
  const maxAxisLabels = 8;
  const labelIndexes = rows.length <= maxAxisLabels
    ? new Set(rows.map((_, index) => index))
    : new Set(Array.from({ length: maxAxisLabels }, (_, index) =>
        Math.round(index * (rows.length - 1) / (maxAxisLabels - 1))
      ));
  const labels = rows.map((row, index) => labelIndexes.has(index)
    ? `<text x="${x(index)}" y="${height - 35}" text-anchor="middle">${escapeHtml(formatMonthYear(row.period))}</text>`
    : "").join("");
  const marks = series.map(item => {
    if (chart.type === "stacked_column") {
      const barWidth = Math.max(16, Math.min(72, (width - pad.left - pad.right) / Math.max(rows.length, 1) * 0.55));
      return rows.map((row, index) => {
        const seriesIndex = series.indexOf(item);
        const previous = series.slice(0, seriesIndex).reduce((sum, prior) => {
          const priorValue = chartNumber(row[prior.key]);
          return sum + (Number.isFinite(priorValue) ? Math.max(0, priorValue) : 0);
        }, 0);
        const value = chartNumber(row[item.key]);
        if (!Number.isFinite(value)) return "";
        const top = y(previous + Math.max(0, value));
        const bottom = y(previous);
        return `<rect x="${x(index) - barWidth / 2}" y="${top}" width="${barWidth}" height="${Math.max(0, bottom - top)}" fill="${item.color}"><title>${escapeHtml(`${item.label} · ${row.period}: ${formatNumber(value, 2)} GWh`)}</title></rect>`;
      }).join("");
    }
    if (chart.type === "column") {
      const groupWidth = Math.max(4, (width - pad.left - pad.right) / Math.max(rows.length, 1) * 0.65);
      const barWidth = groupWidth / series.length;
      return rows.map((row, index) => {
        const value = chartNumber(row[item.key]);
        if (!Number.isFinite(value)) return "";
        const seriesIndex = series.indexOf(item);
        const baseline = y(0);
        const top = Math.min(y(value), baseline);
        return `<rect x="${x(index) - groupWidth / 2 + seriesIndex * barWidth}" y="${top}" width="${Math.max(2, barWidth - 1)}" height="${Math.abs(baseline - y(value))}" fill="${item.color}"><title>${escapeHtml(`${item.label} · ${row.period}: ${formatNumber(value, 2)}`)}</title></rect>`;
      }).join("");
    }
    let output = "", segment = [];
    const flush = () => { if (segment.length > 1) output += `<polyline points="${segment.join(" ")}" fill="none" stroke="${item.color}" stroke-width="3"></polyline>`; segment = []; };
    rows.forEach((row, index) => {
      const value = chartNumber(row[item.key]);
      if (!Number.isFinite(value)) { flush(); return; }
      segment.push(`${x(index)},${y(value)}`);
      output += `<circle cx="${x(index)}" cy="${y(value)}" r="4" fill="#fff" stroke="${item.color}" stroke-width="2"><title>${escapeHtml(`${item.label} · ${row.period}: ${formatNumber(value, 2)}`)}</title></circle>`;
    });
    flush();
    return output;
  }).join("");
  container.innerHTML = `<div class="coal-chart-legend">${series.map(item => `<span><i style="background:${item.color}"></i>${escapeHtml(item.label)}</span>`).join("")}</div>` +
    `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(chart.title)}">${grid}${labels}${marks}` +
    `<text class="axis-title" x="${width / 2}" y="${height - 5}" text-anchor="middle">${escapeHtml(chart.x_label)}</text>` +
    `<text class="axis-title" transform="translate(15 ${height / 2}) rotate(-90)" text-anchor="middle">${escapeHtml(chart.y_label)}</text></svg>`;
}

function selectedCoalAnalysisRows() {
  const rows = state.coalAnalysis?.annual || [];
  const from = document.getElementById("coal-analysis-from").value;
  const to = document.getElementById("coal-analysis-to").value;
  const start = Math.min(rows.findIndex(row => row.period === from), rows.findIndex(row => row.period === to));
  const end = Math.max(rows.findIndex(row => row.period === from), rows.findIndex(row => row.period === to));
  return rows.slice(Math.max(0, start), end + 1);
}

function renderCoalAnalysis() {
  const rows = selectedCoalAnalysisRows();
  if (!rows.length) return;
  const latest = rows[rows.length - 1];
  setText("coal-kpi-production", `${formatNumber(latest.production_mt, 1)} MT`);
  setText("coal-kpi-imports", `${formatNumber(latest.total_imports_mt, 1)} MT`);
  setText("coal-kpi-offtake", `${formatNumber(latest.offtake_mt, 1)} MT`);
  setText("coal-kpi-stock", `${formatNumber(latest.closing_stock_mt, 1)} MT`);
  setText("coal-kpi-dependency", `${formatNumber(latest.import_dependency_pct, 1)}%`);
  setText("coal-kpi-production-change", `${latest.period} · ${signedPercent(latest.production_yoy_pct)} YoY`);
  setText("coal-kpi-imports-change", `${latest.period} · ${signedPercent(latest.imports_yoy_pct)} YoY`);
  setText("coal-kpi-offtake-detail", `${latest.period} · ${formatNumber(latest.offtake_mt / latest.production_mt * 100, 1)}% of production`);
  setText("coal-kpi-stock-detail", `${latest.period} · pit-head closing inventory`);
  setText("coal-kpi-dependency-detail", `${latest.period} · imports ÷ available supply`);
  setCoalKpiBar("coal-kpi-production-bar", latest.production_mt, 1100);
  setCoalKpiBar("coal-kpi-imports-bar", latest.total_imports_mt, 300);
  setCoalKpiBar("coal-kpi-offtake-bar", latest.offtake_mt, 1100);
  setCoalKpiBar("coal-kpi-stock-bar", latest.closing_stock_mt, 130);
  setCoalKpiBar("coal-kpi-dependency-bar", latest.import_dependency_pct, 30);

  renderCoalLineChart("coal-production-imports-chart", rows, [
    ["Production", "production_mt", "#003671"],
    ["Imports", "total_imports_mt", "#db2f34"]
  ], "MT");
  renderCoalLineChart("coal-yoy-chart", rows.slice(1), [
    ["Production YoY", "production_yoy_pct", "#003671"],
    ["Imports YoY", "imports_yoy_pct", "#db2f34"]
  ], "%", true);
  renderCoalLineChart("coal-stock-offtake-chart", rows, [
    ["Off-take", "offtake_mt", "#2e6d92"],
    ["Pit-head stock", "closing_stock_mt", "#d8902f"]
  ], "MT");
  renderCoalImportMix(rows);
  renderCoalFindings(rows);
  renderCoalAnalysisTable(rows);
  applyCoalAnalysisView();
}

function setCoalKpiBar(id, value, maximum) {
  const element = document.getElementById(id);
  if (element) element.style.setProperty("--value", `${Math.min(100, Math.max(2, Number(value || 0) / maximum * 100))}%`);
}

function renderCoalLineChart(id, rows, series, unit, includeZero = false) {
  const container = document.getElementById(id);
  if (!container || rows.length < 2) {
    if (container) container.innerHTML = `<div class="coal-empty">At least two periods are required.</div>`;
    return;
  }
  const width = 720;
  const height = 250;
  const pad = { left: 52, right: 18, top: 18, bottom: 42 };
  const values = rows.flatMap(row => series.map(item => Number(row[item[1]])).filter(Number.isFinite));
  let min = includeZero ? Math.min(0, ...values) : 0;
  let max = Math.max(...values, 1);
  if (includeZero) {
    const span = Math.max(max - min, 1);
    min -= span * 0.08;
    max += span * 0.08;
  } else {
    max *= 1.08;
  }
  const x = index => pad.left + index / (rows.length - 1) * (width - pad.left - pad.right);
  const y = value => pad.top + (max - Number(value)) / (max - min) * (height - pad.top - pad.bottom);
  const ticks = Array.from({ length: 5 }, (_, index) => min + (max - min) * index / 4);
  const grid = ticks.map(value =>
    `<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${width - pad.right}" y2="${y(value).toFixed(1)}" stroke="#e6eaed"></line>` +
    `<text x="${pad.left - 8}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end">${formatNumber(value, unit === "%" ? 0 : 0)}</text>`
  ).join("");
  const xLabels = rows.map((row, index) =>
    `<text x="${x(index).toFixed(1)}" y="${height - 17}" text-anchor="middle">${escapeHtml(row.period.slice(2))}</text>`
  ).join("");
  const lines = series.map(item => {
    const points = rows.map((row, index) => `${x(index).toFixed(1)},${y(row[item[1]]).toFixed(1)}`).join(" ");
    const marks = rows.map((row, index) =>
      `<circle class="coal-chart-point" cx="${x(index).toFixed(1)}" cy="${y(row[item[1]]).toFixed(1)}" r="4" fill="#fff" stroke="${item[2]}" stroke-width="2.3">` +
      `<title>${escapeHtml(`${item[0]} · ${row.period}: ${formatNumber(row[item[1]], 1)} ${unit}`)}</title></circle>`
    ).join("");
    return `<polyline points="${points}" fill="none" stroke="${item[2]}" stroke-width="3"></polyline>${marks}`;
  }).join("");
  container.innerHTML =
    `<div class="coal-chart-legend">${series.map(item => `<span><i style="background:${item[2]}"></i>${escapeHtml(item[0])}</span>`).join("")}</div>` +
    `<svg viewBox="0 0 ${width} ${height}" role="img">${grid}${includeZero && min < 0 ? `<line x1="${pad.left}" y1="${y(0)}" x2="${width - pad.right}" y2="${y(0)}" stroke="#7f8991" stroke-width="1.3"></line>` : ""}${xLabels}${lines}</svg>`;
}

function renderCoalImportMix(rows) {
  const container = document.getElementById("coal-import-mix-chart");
  const max = Math.max(...rows.map(row => Number(row.total_imports_mt || 0)), 1);
  container.innerHTML = `<div class="coal-chart-legend"><span><i style="background:#8c2e3d"></i>Coking</span><span><i style="background:#d8902f"></i>Non-coking</span></div>` +
    `<div class="coal-stacked-bars">${rows.map(row => {
      const coking = Number(row.coking_imports_mt || 0);
      const nonCoking = Number(row.non_coking_imports_mt || 0);
      return `<div class="coal-stacked-row"><span>${escapeHtml(row.period)}</span><div title="${escapeAttr(`${row.period}: ${formatNumber(coking, 1)} MT coking; ${formatNumber(nonCoking, 1)} MT non-coking`)}"><i style="width:${coking / max * 100}%;background:#8c2e3d"></i><i style="width:${nonCoking / max * 100}%;background:#d8902f"></i></div><strong>${formatNumber(row.total_imports_mt, 1)}</strong></div>`;
    }).join("")}</div>`;
}

function renderCoalFindings(rows) {
  const first = rows[0];
  const latest = rows[rows.length - 1];
  const productionChange = latest.production_mt - first.production_mt;
  const importsChange = latest.total_imports_mt - first.total_imports_mt;
  const dependencyChange = latest.import_dependency_pct - first.import_dependency_pct;
  const pairs = rows.filter(row => Number.isFinite(row.production_mt) && Number.isFinite(row.total_imports_mt));
  const corr = pearson(
    pairs.map(row => row.production_mt),
    pairs.map(row => row.total_imports_mt)
  );
  document.getElementById("coal-analysis-findings").innerHTML = [
    ["Production change", `${signedNumber(productionChange)} MT`, `${first.period} to ${latest.period}`],
    ["Import change", `${signedNumber(importsChange)} MT`, `${first.period} to ${latest.period}`],
    ["Import-dependency change", `${signedNumber(dependencyChange)} pp`, `${formatNumber(first.import_dependency_pct, 1)}% to ${formatNumber(latest.import_dependency_pct, 1)}%`],
    ["Production/import correlation", Number.isFinite(corr) ? corr.toFixed(2) : "n/a", `${pairs.length} aligned financial years`]
  ].map(item => `<div><span>${escapeHtml(item[0])}</span><strong>${escapeHtml(item[1])}</strong><small>${escapeHtml(item[2])}</small></div>`).join("") +
    `<p>Correlation describes co-movement only. Pit-head closing stock is not the same as power-station stock-cover days.</p>`;
}

function renderCoalAnalysisTable(rows) {
  document.getElementById("coal-analysis-table").innerHTML =
    `<table><thead><tr><th>FY</th><th>Production MT</th><th>Imports MT</th><th>Off-take MT</th><th>Stock MT</th><th>Import dependency</th></tr></thead><tbody>` +
    rows.map(row => `<tr><td><strong>${escapeHtml(row.period)}</strong></td><td>${formatNumber(row.production_mt, 1)}</td><td>${formatNumber(row.total_imports_mt, 1)}</td><td>${formatNumber(row.offtake_mt, 1)}</td><td>${formatNumber(row.closing_stock_mt, 1)}</td><td>${formatNumber(row.import_dependency_pct, 1)}%</td></tr>`).join("") +
    `</tbody></table>`;
}

function applyCoalAnalysisView() {
  document.querySelectorAll("[data-analysis-panel]").forEach(panel => {
    panel.hidden = false;
  });
}

function pearson(left, right) {
  if (left.length < 3 || left.length !== right.length) return NaN;
  const leftMean = left.reduce((sum, value) => sum + value, 0) / left.length;
  const rightMean = right.reduce((sum, value) => sum + value, 0) / right.length;
  const numerator = left.reduce((sum, value, index) => sum + (value - leftMean) * (right[index] - rightMean), 0);
  const leftSq = left.reduce((sum, value) => sum + (value - leftMean) ** 2, 0);
  const rightSq = right.reduce((sum, value) => sum + (value - rightMean) ** 2, 0);
  return numerator / Math.sqrt(leftSq * rightSq);
}

function signedPercent(value) {
  return `${Number(value) >= 0 ? "+" : ""}${formatNumber(value, 1)}%`;
}

function signedNumber(value) {
  return `${Number(value) >= 0 ? "+" : ""}${formatNumber(value, 1)}`;
}

async function loadCoalMasterCatalog() {
  if (state.coalMaster) return state.coalMaster;
  const response = await fetch("/api/coal/master");
  if (!response.ok) throw new Error("Official coal master could not be loaded");
  state.coalMaster = await response.json();
  return state.coalMaster;
}

function renderCoalMasterOverview(summaryMaster) {
  const master = state.coalMaster || null;
  const coverage = master?.coverage || summaryMaster || {};
  const generatedAt = master?.generated_at || summaryMaster?.generated_at;
  setText("coal-kpi-sources", Number(coverage.source_file_count || summaryMaster?.source_file_count || 0).toLocaleString());
  setText("coal-kpi-files", Number(coverage.extracted_file_count || summaryMaster?.extracted_file_count || 0).toLocaleString());
  setText("coal-kpi-rows", Number(coverage.normalized_row_count || summaryMaster?.normalized_row_count || 0).toLocaleString());
  setText("coal-kpi-tables", Number((master?.source_tables || []).length || summaryMaster?.source_table_count || 0).toLocaleString());
  setText("coal-kpi-fetched", generatedAt ? humanDate(generatedAt) : "-");

  const coverageBox = document.getElementById("coal-master-coverage");
  if (coverageBox) {
    coverageBox.innerHTML = [
      ["Country", coverage.country || "India"],
      ["Requested period", coverage.years_requested || "FY2016-17 to latest official"],
      ["Extract mode", coverage.current_extract_mode || "Official source-backed"],
      ["Quality status", labelize(master?.quality?.status || summaryMaster?.status || "source catalogued")]
    ].map(([label, value]) =>
      `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`
    ).join("");
  }

  if (!master) {
    loadCoalMasterCatalog()
      .then(payload => {
        state.coalMaster = payload;
        renderCoalMasterOverview(summaryMaster);
      })
      .catch(error => {
        const catalog = document.getElementById("coal-source-catalog");
        if (catalog) catalog.innerHTML = `<div class="coal-empty">${escapeHtml(error.message)}</div>`;
      });
    return;
  }

  renderCoalDatasetMix(master.source_tables || []);
  renderCoalSourceCatalog(master.source_tables || []);
}

function renderCoalDatasetMix(tables) {
  const container = document.getElementById("coal-dataset-mix");
  if (!container) return;
  const grouped = {};
  tables.forEach(item => {
    const key = item.dataset_type || "source_reference";
    grouped[key] = (grouped[key] || 0) + Number(item.rows || 0);
  });
  const rows = Object.entries(grouped)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 8);
  if (!rows.length) {
    container.innerHTML = `<div class="coal-empty">Run the official coal fetcher to populate source-backed tables.</div>`;
    return;
  }
  const max = Math.max(...rows.map(([, value]) => value), 1);
  container.innerHTML = rows.map(([key, value]) =>
    `<div class="coal-master-bar"><div><span>${escapeHtml(labelize(key))}</span><strong>${Number(value).toLocaleString()} rows</strong></div>` +
    `<div><i style="width:${Math.max(1, value / max * 100)}%"></i></div></div>`
  ).join("");
}

function renderCoalSourceCatalog(tables) {
  const container = document.getElementById("coal-source-catalog");
  if (!container) return;
  if (!tables.length) {
    container.innerHTML = `<div class="coal-empty">No official source tables have been extracted yet.</div>`;
    return;
  }
  const rows = tables.slice(0, 12);
  container.innerHTML =
    `<table><thead><tr><th>Dataset</th><th>Sheet</th><th>Rows</th></tr></thead><tbody>` +
    rows.map(item =>
      `<tr><td><strong>${escapeHtml(item.source_title || "Official source")}</strong><small>${escapeHtml(labelize(item.dataset_type || "source_reference"))}</small></td>` +
      `<td>${escapeHtml(item.sheet_name || "-")}</td><td>${Number(item.rows || 0).toLocaleString()}</td></tr>`
    ).join("") +
    `</tbody></table>${tables.length > rows.length ? `<p class="table-limit">Showing ${rows.length} of ${tables.length} official source tables. Download the catalog for the full list.</p>` : ""}`;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function refreshCoalActionState() {
  const available = new Set(state.coalSummary?.available_dataset_types || []);
  ["production", "imports", "power_use", "renewables"].forEach(item => available.add(item));
  const selected = document.getElementById("coal-metric").value;
  document.getElementById("coal-export").disabled = !available.has(selected);
  document.getElementById("coal-run-analysis").disabled = false;
}

function selectedCoalKinds() {
  return new Set(
    Array.from(document.querySelectorAll("#coal-workspace-layers input:checked, #coal-consumer-layers input:checked"))
      .map(input => input.value)
  );
}

function renderCoalLayers() {
  state.coalLayer.clearLayers();
  if (state.mode !== "coal" || state.coalView !== "map") {
    updateMapStatus();
    return;
  }
  const selected = selectedCoalKinds();
  const renderer = L.canvas({ padding: 0.5 });
  state.coalAssets.forEach(point => {
    if (!selected.has(point.asset_kind)) return;
    const config = COAL_ASSET_CONFIG[point.asset_kind];
    const lat = Number(point.lat);
    const lon = Number(point.lon);
    if (!config || !Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const marker = L.circleMarker([lat, lon], {
      renderer,
      radius: config.radius,
      color: "#ffffff",
      weight: 0.55,
      fillColor: config.color,
      fillOpacity: 0.9
    });
    marker.bindTooltip(assetTooltip(config, point), {
      className: "asset-tooltip", direction: "top", opacity: 1
    });
    marker.on("click", event => {
      if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
      showAssetCard(config, point);
    });
    marker.addTo(state.coalLayer);
  });
  state.coalLayer._pointCount = state.coalLayer.getLayers().length;
  renderCoalAssetViews();
  updateMapStatus();
}

function setCoalView(view) {
  state.coalView = view;
  document.querySelectorAll("[data-coal-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.coalView === view);
  });
  const dataSurface = document.getElementById("coal-data-surface");
  const nppSurface = document.getElementById("npp-power-surface");
  const mapElement = document.getElementById("map");
  const isAnalytics = view === "analytics";
  const isMap = view === "map";
  const isPower = view === "power";
  dataSurface.hidden = isMap || isPower || state.mode !== "coal";
  nppSurface.hidden = !isPower || state.mode !== "coal";
  mapElement.hidden = !isMap && state.mode === "coal";
  document.querySelector(".map-topbar").hidden = !isMap && state.mode === "coal";
  document.querySelector(".map-key").hidden = !isMap && state.mode === "coal";
  document.getElementById("coal-assets-table").hidden = view !== "table";
  document.getElementById("coal-assets-cards").hidden = view !== "cards";
  document.querySelector(".coal-surface-heading").hidden = isAnalytics;
  if (isAnalytics && !dataSurface.hidden) dataSurface.scrollTop = 0;
  document.getElementById("coal-surface-title").textContent =
    view === "cards" ? "India coal asset cards" : "India coal asset table";
  if (isPower && state.mode === "coal") loadNppPower();
  if (isMap) {
    setTimeout(() => {
      state.map.invalidateSize();
      state.map.fitBounds([[6, 68], [37, 98]], { padding: [25, 25] });
      renderCoalLayers();
    }, 0);
  } else {
    state.coalLayer.clearLayers();
    renderCoalAssetViews();
  }
}

function filteredCoalAssets() {
  const selected = selectedCoalKinds();
  return state.coalAssets.filter(item => selected.has(item.asset_kind));
}

function renderCoalAssetViews() {
  const rows = filteredCoalAssets();
  const table = document.getElementById("coal-assets-table");
  const cards = document.getElementById("coal-assets-cards");
  const visibleRows = rows.slice(0, 1000);
  const cardRows = rows
    .filter(item => !["coal_mines", "iron_ore_mines"].includes(item.asset_kind))
    .sort((left, right) =>
    Number(right.asset_kind === "coal_trade_terminals") -
    Number(left.asset_kind === "coal_trade_terminals")
  );
  table.innerHTML = visibleRows.length
    ? `<table><thead><tr><th>Asset</th><th>Type</th><th>Status / role</th><th>Capacity</th><th>Source</th></tr></thead><tbody>` +
      visibleRows.map(item => `<tr><td><strong>${escapeHtml(item.name || "Unnamed")}</strong><small>${escapeHtml(item.country || "India")}</small></td>` +
        `<td>${escapeHtml(item.asset_label || labelize(item.asset_kind))}</td>` +
        `<td>${escapeHtml(item.status || item.asset_type || "Unknown")}${item.project_status && item.project_status !== item.status ? `<small>${escapeHtml(item.project_status)}</small>` : ""}</td>` +
        `<td>${item.capacity == null ? "Unknown" : escapeHtml(Number(item.capacity).toLocaleString() + " " + (item.capacity_unit || ""))}${item.expansion_capacity == null ? "" : `<small>Expansion +${escapeHtml(Number(item.expansion_capacity).toLocaleString() + " " + (item.capacity_unit || "Mtpa"))}</small>`}</td>` +
        `<td>${escapeHtml(item.source_text || "GEM / WPI")}</td></tr>`).join("") +
      `</tbody></table>${rows.length > visibleRows.length ? `<p class="table-limit">Showing first ${visibleRows.length.toLocaleString()} of ${rows.length.toLocaleString()} assets.</p>` : ""}`
    : `<div class="coal-empty">Select at least one verified map layer.</div>`;
  cards.innerHTML = cardRows.length
    ? cardRows.slice(0, 120).map(item => `<article class="${item.port_specification_available ? "coal-port-card" : ""}"><span>${escapeHtml(item.asset_label || labelize(item.asset_kind))}</span>` +
        `<h3>${escapeHtml(item.name || "Unnamed asset")}</h3>` +
        `<p>${escapeHtml(item.status || item.asset_type || "Status unknown")}</p>` +
        `<small>${item.capacity == null ? "Capacity unknown" : escapeHtml(Number(item.capacity).toLocaleString() + " " + (item.capacity_unit || ""))}${item.expansion_capacity == null ? "" : `<br>Expansion +${escapeHtml(Number(item.expansion_capacity).toLocaleString() + " " + (item.capacity_unit || "Mtpa"))}`}</small>` +
        (item.port_specification_available
          ? `<button type="button" class="coal-card-action" data-port-spec-id="${escapeAttr(item.id)}">View port details</button>`
          : item.asset_kind === "power_consumers"
            ? `<button type="button" class="coal-card-action" data-plant-spec-id="${escapeAttr(item.id)}">View plant details</button>`
          : "") +
        `</article>`).join("")
    : `<div class="coal-empty">Mine assets are available in map and table views. Select a terminal or consuming-industry layer to use card view.</div>`;
  cards.querySelectorAll("[data-port-spec-id]").forEach(button => {
    button.addEventListener("click", () => {
      const asset = state.coalAssets.find(item => item.id === button.dataset.portSpecId);
      if (asset) showCoalPortDetails(asset);
    });
  });
  cards.querySelectorAll("[data-plant-spec-id]").forEach(button => {
    button.addEventListener("click", () => {
      const asset = state.coalAssets.find(item => item.id === button.dataset.plantSpecId);
      if (asset) showAssetCard(COAL_ASSET_CONFIG.power_consumers, asset);
    });
  });
}

async function uploadCoalDataset() {
  const input = document.getElementById("coal-upload-input");
  const file = input.files?.[0];
  if (!file) return;
  const message = document.getElementById("coal-upload-message");
  const datasetType = document.getElementById("coal-metric").value;
  const form = new FormData();
  form.append("file", file);
  message.textContent = `Uploading ${file.name}…`;
  try {
    const response = await fetch(`/api/coal/upload?dataset_type=${encodeURIComponent(datasetType)}`, {
      method: "POST", body: form
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Upload failed");
    message.textContent = `${payload.dataset_label}: ${Number(payload.rows).toLocaleString()} rows uploaded. Quality status: ${labelize(payload.quality_status)}.`;
    await loadCoalWorkspace();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    input.value = "";
  }
}

async function runCoalResearch() {
  const input = document.getElementById("coal-research-question");
  const message = document.getElementById("coal-research-message");
  const question = input.value.trim();
  if (question.length < 4) {
    message.textContent = "Write a specific question first.";
    input.focus();
    return;
  }
  const button = document.getElementById("coal-research-run");
  button.disabled = true;
  message.textContent = "Matching your question to official datasets…";
  try {
    const response = await fetch("/api/coal/research/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Analysis failed");
    state.coalResearch = payload;
    renderCoalResearch(payload);
    message.textContent = `${payload.rows.length} official observations returned. Ctrl+Enter runs another question.`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderCoalResearch(payload) {
  const panel = document.getElementById("coal-research-result");
  panel.hidden = false;
  setText("coal-research-title", payload.title);
  setText("coal-research-status", payload.status.toUpperCase());
  setText("coal-research-unit", payload.unit);
  setText("coal-research-answer", payload.answer);
  renderCoalResearchChart(payload);
  const columns = payload.columns || [];
  const rows = (payload.rows || []).slice(0, 20);
  document.getElementById("coal-research-table").innerHTML =
    `<table><thead><tr>${columns.map(column => `<th>${escapeHtml(labelize(column))}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(row => `<tr>${columns.map(column => `<td>${formatResearchValue(row[column])}</td>`).join("")}</tr>`).join("") +
    `</tbody></table>${payload.rows.length > rows.length ? `<p class="table-limit">Top ${rows.length} shown; the download contains the complete filtered result.</p>` : ""}`;
  document.getElementById("coal-research-sources").innerHTML =
    `<small>${escapeHtml(payload.guardrail)}</small>` +
    payload.sources.map(source => `<a href="${escapeAttr(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title)}</a>`).join("");
  const encoded = encodeURIComponent(payload.question);
  document.getElementById("coal-research-csv").href = `/api/coal/research/export?format=csv&q=${encoded}`;
  document.getElementById("coal-research-xlsx").href = `/api/coal/research/export?format=xlsx&q=${encoded}`;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function formatResearchValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return escapeHtml(formatNumber(value, Math.abs(value) < 100 ? 2 : 1));
  return escapeHtml(String(value));
}

function renderCoalResearchChart(payload) {
  const container = document.getElementById("coal-research-chart");
  const rows = payload.rows || [];
  const series = payload.chart?.series || [];
  const category = payload.chart?.category || "period";
  if (!rows.length || !series.length) {
    container.innerHTML = `<div class="coal-empty">No chartable observations.</div>`;
    return;
  }
  if (payload.chart.type !== "bar") {
    renderCoalLineChart(container.id, rows, series.map(item => [item.label, item.key, item.color]), payload.unit.includes("%") ? "%" : payload.unit);
    return;
  }
  const chartRows = rows.slice(0, 15);
  const max = Math.max(...chartRows.flatMap(row => series.map(item => Number(row[item.key] || 0))), 1);
  container.innerHTML = `<div class="coal-chart-legend">${series.map(item => `<span><i style="background:${item.color}"></i>${escapeHtml(item.label)}</span>`).join("")}</div>` +
    `<div class="coal-research-bars">${chartRows.map(row =>
      `<div><span title="${escapeAttr(String(row[category] || ""))}">${escapeHtml(String(row[category] || ""))}</span><section>${series.map(item => `<i style="width:${Math.max(1, Number(row[item.key] || 0) / max * 100)}%;background:${item.color}" title="${escapeAttr(`${item.label}: ${formatNumber(row[item.key], 2)} ${payload.unit}`)}"></i>`).join("")}</section><strong>${formatNumber(row[series[0].key], 2)}</strong></div>`
    ).join("")}</div>`;
}

async function exportCoalData() {
  const datasetType = document.getElementById("coal-metric").value;
  const frequency = document.getElementById("coal-frequency").value;
  const coalType = document.getElementById("coal-grade").value;
  const period = document.getElementById("coal-period").value;
  const params = new URLSearchParams({ dataset_type: datasetType, frequency, coal_type: coalType, period });
  const response = await fetch(`/api/coal/export?${params}`);
  if (!response.ok) {
    const payload = await response.json();
    document.getElementById("coal-upload-message").textContent = payload.detail || "Export failed";
    return;
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `india_coal_${datasetType}_${frequency}.xlsx`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function loadNppPower(force = false) {
  const refreshButton = document.getElementById("npp-refresh");
  const freshness = document.getElementById("npp-freshness");
  refreshButton.disabled = true;
  freshness.textContent = force ? "Refreshing from official NPP source…" : "Loading latest validated NPP snapshot…";
  try {
    const response = await fetch(`/api/npp/power-dashboard${force ? "?force=true" : ""}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "NPP data is unavailable");
    document.getElementById("npp-installed-capacity").textContent =
      `${formatNumber(data.installed_capacity_mw / 1000, 1)} GW`;
    document.getElementById("npp-reported-date").textContent =
      `NPP source date ${humanDate(data.source_reported_date)}`;
    const demand = data.daily_demand?.[0];
    document.getElementById("npp-demand-met").textContent = demand
      ? `${formatNumber(demand.demand_met_mw / 1000, 1)} GW`
      : "Unavailable";
    document.getElementById("npp-demand-date").textContent = demand
      ? `Reported ${escapeHtml(demand.date || "")}`
      : "No daily-demand row supplied";
    const status = data.all_india_status || {};
    renderNppBars("npp-status-chart", [
      { label: "Online", value: status.online_capacity_mw, color: "#2c8a63" },
      { label: "Under maintenance", value: status.under_maintenance_capacity_mw, color: "#e9a823" },
      { label: "Shutdown", value: status.shutdown_capacity_mw, color: "#db2f34" },
      { label: "Unscheduled", value: status.unscheduled_capacity_mw, color: "#8b65b6" }
    ], "MW");
    const categoryColors = ["#6f7782", "#296fba", "#8b65b6", "#629c4d"];
    renderNppBars(
      "npp-category-chart",
      (data.category_capacity || []).map((item, index) => ({
        label: item.label, value: item.mw, color: categoryColors[index] || "#003671"
      })),
      "MW"
    );
    const sectorColors = ["#003671", "#55a6c8", "#db2f34"];
    renderNppBars(
      "npp-sector-chart",
      (data.sector_capacity || []).map((item, index) => ({
        label: item.label, value: item.mw, color: sectorColors[index] || "#003671"
      })),
      "MW"
    );
    renderNppBars("npp-demand-chart", demand ? [
      { label: "Peak requirement", value: demand.peak_requirement_mw, color: "#1c294a" },
      { label: "Demand met", value: demand.demand_met_mw, color: "#2c8a63" },
      { label: "Reported deficit", value: Math.abs(demand.deficit_mw), color: "#db2f34" }
    ] : [], "MW");
    const generation = data.daily_generation || {};
    renderNppBars("npp-daily-generation-chart", generation.date ? [
      { label: `Actual · ${humanDate(generation.date)}`, value: generation.actual_mu, color: "#2c8a63" },
      { label: "Programme", value: generation.program_mu, color: "#003671" },
      { label: `Prior year · ${humanDate(generation.prior_year_date)}`, value: generation.prior_year_actual_mu, color: "#8b65b6" }
    ] : [], "MU", 1);
    document.getElementById("npp-generation-period").textContent = generation.date
      ? `${humanDate(generation.date)} · ${formatNumber(generation.deviation_percent, 1)}% vs programme`
      : "Official daily-generation row unavailable";
    const stock = data.coal_stock_availability || {};
    const stockColors = { "Non-pithead stations": "#db2f34", "Pithead stations": "#e9a823" };
    renderNppBars(
      "npp-coal-stock-chart",
      (stock.rows || []).map(row => ({
        label: `${row.stock_cover_band} · ${row.station_type}`,
        value: row.station_count,
        color: stockColors[row.station_type] || "#6f7782"
      })),
      "stations"
    );
    document.getElementById("npp-coal-stock-period").textContent = stock.date
      ? `As on ${humanDate(stock.date)} · counts by stock-cover band`
      : "Official coal-stock row unavailable";
    const cumulative = data.cumulative_generation || {};
    renderNppBars("npp-cumulative-generation-chart", cumulative.period_end ? [
      { label: `${humanDate(cumulative.period_start)} – ${humanDate(cumulative.period_end)}`, value: cumulative.actual_mu, color: "#2c8a63" },
      { label: "Programme for current period", value: cumulative.program_mu, color: "#003671" },
      { label: `${humanDate(cumulative.prior_period_start)} – ${humanDate(cumulative.prior_period_end)}`, value: cumulative.prior_year_actual_mu, color: "#8b65b6" }
    ] : [], "MU", 1);
    document.getElementById("npp-cumulative-period").textContent = cumulative.period_end
      ? `${formatNumber(cumulative.deviation_percent, 1)}% vs programme`
      : "Official cumulative-generation row unavailable";
    const thermalPlf = data.sector_plf?.thermal_current;
    const nuclearPlf = data.sector_plf?.nuclear_current;
    const plfRows = thermalPlf ? [
      { label: "Thermal · All India", value: thermalPlf.all_india_percent, color: "#db2f34" },
      { label: "Thermal · Central", value: thermalPlf.central_percent, color: "#003671" },
      { label: "Thermal · State", value: thermalPlf.state_percent, color: "#55a6c8" },
      { label: "Thermal · Private", value: thermalPlf.private_percent, color: "#e9a823" }
    ] : [];
    if (nuclearPlf) {
      plfRows.push(
        { label: "Nuclear · All India", value: nuclearPlf.all_india_percent, color: "#8b65b6" },
        { label: "Nuclear · Central", value: nuclearPlf.central_percent, color: "#66508d" }
      );
    }
    renderNppBars("npp-sector-plf-chart", plfRows, "%", 1);
    document.getElementById("npp-plf-period").textContent = thermalPlf
      ? `${thermalPlf.category} ${thermalPlf.report_type || ""} · FY ${thermalPlf.financial_year || "unavailable"}`
      : "Official PLF row unavailable";
    renderNppHistory(data.historical_installed_capacity || []);
    const fetchedAt = data.fetched_at ? new Date(data.fetched_at).toLocaleString() : "unknown";
    freshness.textContent = data.stale
      ? `Showing last validated cache · refresh failed · fetched ${fetchedAt}`
      : `Validated from NPP · fetched ${fetchedAt} · auto-refresh every ${formatRefreshInterval(data.refresh_interval_seconds || 43200)}`;
    freshness.classList.toggle("stale", Boolean(data.stale));
    document.getElementById("npp-quality-note").textContent =
      "Category and sector totals reconcile to the NPP installed-capacity headline. Shutdown and unscheduled values are supporting status measures and are not added to the capacity total.";
    state.nppLoaded = true;
    if (!state.nppRefreshTimer) {
      state.nppRefreshTimer = setInterval(
        () => loadNppPower(false),
        Math.max(60, Number(data.refresh_interval_seconds || 43200)) * 1000
      );
    }
  } catch (error) {
    freshness.textContent = error.message;
    freshness.classList.add("stale");
    document.getElementById("npp-quality-note").textContent =
      "No unvalidated fallback values are displayed. Retry when the official NPP source is available.";
  } finally {
    refreshButton.disabled = false;
  }
}

function renderNppBars(id, rows, unit, digits = 0) {
  const container = document.getElementById(id);
  if (!rows.length) {
    container.innerHTML = `<div class="coal-empty">Official source row unavailable.</div>`;
    return;
  }
  const max = Math.max(...rows.map(row => Number(row.value || 0)), 1);
  container.innerHTML = rows.map(row =>
    `<div class="npp-bar-row"><div><span>${escapeHtml(row.label)}</span><strong>${formatNumber(row.value, digits)} ${escapeHtml(unit)}</strong></div>` +
    `<div class="npp-bar-track"><i style="width:${Math.max(0.5, Number(row.value || 0) / max * 100)}%;background:${escapeAttr(row.color)}"></i></div></div>`
  ).join("");
}

function renderNppHistory(rows) {
  const container = document.getElementById("npp-history-chart");
  if (rows.length < 2) {
    container.innerHTML = `<div class="coal-empty">Historical installed-capacity series unavailable.</div>`;
    return;
  }
  const width = 920;
  const height = 270;
  const pad = { left: 56, right: 16, top: 16, bottom: 42 };
  const series = [
    ["Thermal", "thermal_mw", "#6f7782", ""],
    ["Hydro", "hydro_mw", "#296fba", "7 3"],
    ["Nuclear", "nuclear_mw", "#8b65b6", "2 3"],
    ["Renewables", "renewables_mw", "#629c4d", "10 3 2 3"]
  ];
  const max = Math.max(...rows.flatMap(row => series.map(item => Number(row[item[1]] || 0))), 1);
  const x = index => pad.left + index / (rows.length - 1) * (width - pad.left - pad.right);
  const y = value => height - pad.bottom - Number(value || 0) / max * (height - pad.top - pad.bottom);
  const yTicks = [0, max / 2, max];
  const grid = yTicks.map(value =>
    `<line x1="${pad.left}" y1="${y(value).toFixed(1)}" x2="${width - pad.right}" y2="${y(value).toFixed(1)}" stroke="#e4e8eb"></line>` +
    `<text x="${pad.left - 8}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#6c7883">${formatNumber(value / 1000, 0)}</text>`
  ).join("");
  const tickCount = Math.min(7, rows.length);
  const tickIndexes = [...new Set(Array.from({ length: tickCount }, (_, index) =>
    Math.round(index * (rows.length - 1) / Math.max(tickCount - 1, 1))
  ))];
  const xTicks = tickIndexes.map(index => {
    const year = rows[index].date?.slice(0, 4) || "";
    return `<line x1="${x(index).toFixed(1)}" y1="${height - pad.bottom}" x2="${x(index).toFixed(1)}" y2="${height - pad.bottom + 5}" stroke="#aeb8c0"></line>` +
      `<text x="${x(index).toFixed(1)}" y="${height - 18}" text-anchor="middle" font-size="10" fill="#6c7883">${escapeHtml(year)}</text>`;
  }).join("");
  const polylines = series.map(item => {
    const points = rows.map((row, index) => `${x(index).toFixed(1)},${y(row[item[1]]).toFixed(1)}`).join(" ");
    const circles = rows.map((row, index) =>
      `<circle class="npp-history-point" cx="${x(index).toFixed(1)}" cy="${y(row[item[1]]).toFixed(1)}" r="3.2" fill="#fff" stroke="${item[2]}" stroke-width="2" tabindex="0" role="img" aria-label="${escapeAttr(`${item[0]}, ${row.date}, ${formatNumber(row[item[1]], 0)} MW`)}" data-series="${escapeAttr(item[0])}" data-date="${escapeAttr(row.date || "")}" data-value="${Number(row[item[1]] || 0)}"></circle>`
    ).join("");
    return `<polyline points="${points}" fill="none" stroke="${item[2]}" stroke-width="2.5" stroke-dasharray="${item[3]}" vector-effect="non-scaling-stroke"></polyline>${circles}`;
  }).join("");
  container.innerHTML =
    `<div class="npp-history-legend">${series.map(item => `<span><i style="background:${item[2]}"></i>${item[0]}</span>`).join("")}<span>Y-axis: GW</span></div>` +
    `<div class="npp-history-plot">` +
    `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Historical growth of installed capacity">` +
    grid + xTicks + polylines +
    `</svg><div class="npp-history-tooltip" hidden><strong></strong><span></span></div></div>`;
  const plot = container.querySelector(".npp-history-plot");
  const tooltip = container.querySelector(".npp-history-tooltip");
  const showTooltip = (point, event) => {
    const value = Number(point.dataset.value || 0);
    tooltip.querySelector("strong").textContent =
      `${point.dataset.series} · ${humanDate(point.dataset.date)}`;
    tooltip.querySelector("span").textContent =
      `${formatNumber(value / 1000, 1)} GW · ${formatNumber(value, 0)} MW`;
    tooltip.hidden = false;
    const bounds = plot.getBoundingClientRect();
    const pointBounds = point.getBoundingClientRect();
    const px = event?.clientX ?? pointBounds.left + pointBounds.width / 2;
    const py = event?.clientY ?? pointBounds.top;
    tooltip.style.left = `${Math.min(bounds.width - 75, Math.max(75, px - bounds.left))}px`;
    tooltip.style.top = `${Math.max(55, py - bounds.top)}px`;
  };
  container.querySelectorAll(".npp-history-point").forEach(point => {
    point.addEventListener("mouseenter", event => showTooltip(point, event));
    point.addEventListener("mousemove", event => showTooltip(point, event));
    point.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    point.addEventListener("focus", () => showTooltip(point));
    point.addEventListener("blur", () => { tooltip.hidden = true; });
  });
}

function formatRefreshInterval(seconds) {
  const hours = Number(seconds || 0) / 3600;
  return hours >= 1
    ? `${formatNumber(hours, Number.isInteger(hours) ? 0 : 1)} hr`
    : `${formatNumber(Number(seconds || 0) / 60, 0)} min`;
}

function formatNumber(value, digits = 0) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function humanDate(value) {
  if (!value) return "unavailable";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function populateSelect(id, defaultLabel, items) {
  const select = document.getElementById(id);
  const current = select.value;
  select.innerHTML = `<option value="">${defaultLabel}</option>` +
    items.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.label)} (${Number(item.count).toLocaleString()})</option>`).join("");
  select.value = current;
}

function portParams() {
  const params = new URLSearchParams({ limit: "10000" });
  const categories = Array.from(document.querySelectorAll("#port-categories input:checked")).map(x => x.value);
  const country = document.getElementById("port-country").value;
  const size = document.getElementById("port-size").value;
  if (categories.length) params.set("categories", categories.join(","));
  if (country) params.set("countries", country);
  if (size) params.set("harbor_sizes", size);
  return params;
}

async function loadPorts() {
  setLoading(true, "Loading ports…");
  try {
    const response = await fetch("/api/map/world_ports?" + portParams());
    if (!response.ok) throw new Error("Could not load ports");
    state.ports = await response.json();
    state.filteredPorts = state.ports;
    state.weatherPortTierCache.clear();
    if (!state.routePortCatalog.length) {
      state.routePortCatalog = [...state.ports].sort((left, right) =>
        String(left.name || "").localeCompare(String(right.name || "")) ||
        String(left.country || "").localeCompare(String(right.country || ""))
      );
      populateRoutePortSearch();
    }
    renderPorts();
  } catch (error) {
    setStatus(error.message);
  } finally {
    setLoading(false);
  }
}

function portDisplayTier(port) {
  const size = String(port.harbor_size || "").toLowerCase();
  const capacity = Number(port.terminal_capacity_mtpa || 0);
  const largeVessel = String(port.max_vessel || "").toLowerCase().includes("over 500");
  if (size === "large" || capacity >= 20 || largeVessel) return 1;
  if (size === "medium" || capacity >= 5 || port.specialist_terminal) return 2;
  if (size === "small") return 3;
  return 4;
}

function portVisibleAtZoom(port, zoom) {
  const tier = portDisplayTier(port);
  if (zoom <= 3) return tier === 1;
  if (zoom === 4) return tier <= 2;
  if (zoom === 5) return tier <= 3;
  return true;
}

function weatherPortMatchName(value) {
  return normalizedPortQuery(value)
    .replace(/\b(?:port|harbour|harbor|pelabuhan|terminal)\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function weatherPortTradingTier(row) {
  const cacheKey = row.location_id || `${row.location_name}:${row.latitude}:${row.longitude}`;
  if (state.weatherPortTierCache.has(cacheKey)) return state.weatherPortTierCache.get(cacheKey);
  const weatherName = weatherPortMatchName(row.location_name || row.zone_name);
  let match = null;
  if (weatherName) {
    match = state.ports.find(port => {
      const names = [port.name, ...(port.search_aliases || [])]
        .map(weatherPortMatchName)
        .filter(Boolean);
      return names.some(name => name === weatherName || (
        Math.min(name.length, weatherName.length) >= 5 &&
        (name.includes(weatherName) || weatherName.includes(name))
      ));
    });
  }
  if (!match && row.latitude != null && row.longitude != null) {
    const lat = Number(row.latitude);
    const lon = Number(row.longitude);
    let nearestDistance = Infinity;
    state.ports.forEach(port => {
      const portLat = Number(port.lat);
      const portLon = Number(port.lon);
      if (!Number.isFinite(portLat) || !Number.isFinite(portLon)) return;
      const latDelta = portLat - lat;
      const lonDelta = (portLon - lon) * Math.cos(lat * Math.PI / 180);
      const distance = latDelta * latDelta + lonDelta * lonDelta;
      if (distance < nearestDistance) {
        nearestDistance = distance;
        match = port;
      }
    });
    // Roughly 25 km at the equator: close enough to treat a BMKG forecast
    // point as belonging to the matched trading port, without merging cities.
    if (nearestDistance > 0.05) match = null;
  }
  const tier = match ? portDisplayTier(match) : 4;
  state.weatherPortTierCache.set(cacheKey, tier);
  return tier;
}

function weatherPortVisibleAtZoom(row, zoom) {
  const tier = weatherPortTradingTier(row);
  if (zoom <= 5) return tier === 1;
  if (zoom === 6) return tier <= 2;
  if (zoom === 7) return tier <= 3;
  return true;
}

function renderPorts() {
  state.portLayer.clearLayers();
  state.renderedPortCount = 0;
  if (!portsAllowedForMode()) {
    document.getElementById("port-visible-count").textContent = state.mode === "ports" ? "hidden" : "overlay off";
    updateMapStatus();
    return;
  }
  const renderer = L.canvas({ padding: 0.5 });
  const zoom = state.map.getZoom();
  const visiblePorts = state.filteredPorts.filter(port =>
    portVisibleAtZoom(port, zoom)
  );
  visiblePorts.forEach(port => {
    const lat = Number(port.lat);
    const lon = Number(port.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const tier = portDisplayTier(port);
    const marker = L.circleMarker([lat, lon], {
      renderer,
      radius: tier === 1 ? 3.2 : tier === 2 ? 2.7 : 2.25,
      color: "#ffffff",
      weight: tier === 1 ? 0.9 : 0.5,
      fillColor: state.coastalWeatherEnabled ? "#2c91b4" : portColor(port.categories),
      fillOpacity: tier === 1 ? 0.94 : 0.82
    });
    marker.bindTooltip(portTooltip(port), { className: "port-tooltip", direction: "top", opacity: 1 });
    marker.on("click", () => handlePortClick(port));
    marker.addTo(state.portLayer);
  });
  state.renderedPortCount = visiblePorts.length;
  const visibilityLabel = zoom <= 3
    ? "major"
    : zoom === 4
      ? "major + regional"
      : zoom === 5
        ? "expanded"
        : "all";
  document.getElementById("port-visible-count").textContent =
    `${visiblePorts.length.toLocaleString()} ${visibilityLabel}`;
  updateMapStatus();
}

function portColor(categories = []) {
  if (categories.includes("coal")) return "#db2f34";
  if (categories.includes("dry_bulk")) return "#b52a2a";
  if (categories.includes("oil")) return "#b36b3f";
  if (categories.includes("container")) return "#258aa5";
  if (categories.includes("lng")) return "#6855a4";
  return "#003671";
}

function portTooltip(port) {
  const cats = (port.categories || []).map(labelize).join(" · ") || "World port";
  return `<strong>${escapeHtml(port.name)}</strong>${escapeHtml(port.country || "")}<br>${escapeHtml(cats)}`;
}

function layerUrl(id) {
  const mode = LAYER_CONFIG[id].mode;
  const prefix = mode === "energy" ? "energy" : "commodity";
  const filters = {
    country: document.getElementById(`${prefix}-country`).value,
    status: document.getElementById(`${prefix}-status`).value
  };
  const params = new URLSearchParams({ limit: "150000" });
  if (filters.country) params.set("country", filters.country);
  if (filters.status) params.set("status", filters.status);
  return `/api/map/${encodeURIComponent(id)}?${params}`;
}

function layerCacheKey(id) {
  const role = id === "coal_trade_terminals"
    ? document.getElementById("coal-terminal-role").value
    : id === "iron_ore_terminals"
      ? document.getElementById("iron-terminal-role").value
      : "";
  return `${layerUrl(id)}|${role}`;
}

async function applyWorkspaceFilters(mode) {
  const prefix = mode === "energy" ? "energy" : "commodity";
  state.filters[mode] = {
    country: document.getElementById(`${prefix}-country`).value,
    status: document.getElementById(`${prefix}-status`).value
  };
  WORKSPACE_LAYERS[mode].forEach(id => {
    state.layerEpoch.set(id, (state.layerEpoch.get(id) || 0) + 1);
    const layer = state.assetLayers.get(id);
    if (layer && state.map.hasLayer(layer)) state.map.removeLayer(layer);
    state.assetLayers.delete(id);
  });
  const checked = WORKSPACE_LAYERS[mode]
    .map(id => workspaceInput(mode, id))
    .filter(input => input?.checked);
  for (const input of checked) await toggleAssetLayer(input);
  updateMapStatus();
}

async function toggleAssetLayer(input) {
  const id = input.value;
  const config = LAYER_CONFIG[id];
  const layer = state.assetLayers.get(id);
  if (!input.checked || config.mode !== state.mode) {
    if (layer && state.map.hasLayer(layer)) state.map.removeLayer(layer);
    updateActiveCounts();
    updateMapStatus();
    return;
  }
  setLoading(true, `Loading ${config.label.toLowerCase()}…`);
  try {
    const epoch = state.layerEpoch.get(id) || 0;
    const cacheKey = layerCacheKey(id);
    let points = state.assetCache.get(cacheKey);
    if (!points) {
      const response = await fetch(layerUrl(id));
      if (!response.ok) throw new Error(`Could not load ${config.label}`);
      points = await response.json();
      if (id === "coal_trade_terminals" || id === "iron_ore_terminals") {
        const role = document.getElementById(
          id === "coal_trade_terminals" ? "coal-terminal-role" : "iron-terminal-role"
        ).value;
        if (role) points = points.filter(point => String(point.asset_type || "").includes(role));
      }
      state.assetCache.set(cacheKey, points);
    }
    if (
      epoch !== (state.layerEpoch.get(id) || 0) ||
      !input.checked ||
      config.mode !== state.mode ||
      cacheKey !== layerCacheKey(id)
    ) return;
    let currentLayer = state.assetLayers.get(id);
    if (!currentLayer) {
      currentLayer = buildAssetLayer(id, points);
      currentLayer._pointCount = points.length;
      state.assetLayers.set(id, currentLayer);
    }
    currentLayer.addTo(state.map);
  } catch (error) {
    input.checked = false;
    setStatus(error.message);
  } finally {
    setLoading(false);
    updateActiveCounts();
    updateMapStatus();
  }
}

function buildAssetLayer(id, points) {
  const config = LAYER_CONFIG[id];
  const group = L.layerGroup();
  const renderer = L.canvas({ padding: 0.5 });
  points.forEach(point => {
    const lat = Number(point.lat);
    const lon = Number(point.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    const marker = L.circleMarker([lat, lon], {
      renderer,
      radius: config.mode === "commodities" ? Math.max(config.radius, 4.5) : config.radius,
      color: "#ffffff",
      weight: config.mode === "commodities" ? 1 : 0.45,
      fillColor: config.color,
      fillOpacity: 0.88,
      interactive: true,
      bubblingMouseEvents: false
    });
    marker.bindTooltip(assetTooltip(config, point), {
      className: "asset-tooltip",
      direction: "top",
      opacity: 1,
      sticky: true
    });
    marker.on("mouseover", () => {
      marker.setStyle({ weight: 2, fillOpacity: 1 });
      marker.openTooltip();
    });
    marker.on("mouseout", () => {
      marker.setStyle({ weight: config.mode === "commodities" ? 1 : 0.45, fillOpacity: 0.88 });
    });
    marker.on("click", event => {
      if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
      if (["iron_ore_mines", "iron_ore_terminals", "steel_plants"].includes(id)) {
        showCommodityAssetCard(config, { ...point, asset_kind: point.asset_kind || point.layer || id });
      } else {
        showAssetCard(config, point);
      }
    });
    marker.addTo(group);
  });
  return group;
}

function assetTooltip(config, point) {
  const displayedCapacity = point.plant_capacity ?? point.capacity;
  const capacity = displayedCapacity == null ? "" :
    `<br>${Number(displayedCapacity).toLocaleString()} ${escapeHtml(point.capacity_unit || "MW")}`;
  const units = point.unit_count == null ? "" :
    `<br>${Number(point.unit_count).toLocaleString()} unit${Number(point.unit_count) === 1 ? "" : "s"}`;
  const expansion = point.expansion_capacity == null ? "" :
    `<br>Expansion: +${Number(point.expansion_capacity).toLocaleString()} ${escapeHtml(point.capacity_unit || "Mtpa")} (${escapeHtml((point.expansion_status || []).join(" + "))})`;
  const role = point.asset_type ? `<br>${escapeHtml(point.asset_type)}` : "";
  return `<strong>${escapeHtml(point.name || config.label)}</strong>` +
    `${escapeHtml(point.country || "")}${point.status ? " · " + escapeHtml(point.status) : ""}${role}${capacity}${units}${expansion}`;
}

function commodityQuantity(value, unit = "ktpa") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (String(unit).toLowerCase() === "ktpa") {
    return `${formatNumber(numeric / 1000, 2)} Mtpa`;
  }
  if (String(unit).toLowerCase() === "kt") {
    return `${formatNumber(numeric / 1000, 2)} Mt`;
  }
  return `${formatNumber(numeric, 1)} ${unit}`;
}

function commodityLocation(point) {
  return [point.location_address, point.municipality, point.subnational_unit, point.region]
    .map(presentPlantValue)
    .filter(Boolean)
    .join(" · ");
}

function showCommodityAssetCard(config, point) {
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card");
  const kind = point.asset_kind || point.layer;
  const capacity = commodityQuantity(point.capacity, point.capacity_unit || "ktpa");
  const coordinates = Number.isFinite(Number(point.lat)) && Number.isFinite(Number(point.lon))
    ? `${formatNumber(point.lat, 5)}, ${formatNumber(point.lon, 5)}`
    : null;
  const sourceLink = point.source_url
    ? `<a class="detail-source-link" href="${escapeAttr(point.source_url)}" target="_blank" rel="noopener">Open GEM source record</a>`
    : "";
  const mineDetails = kind === "iron_ore_mines"
    ? optionalDetailCell("2024 production", commodityQuantity(point.production_2024_ktpa)) +
      optionalDetailCell("2023 production", commodityQuantity(point.production_2023_ktpa)) +
      optionalDetailCell("2022 production", commodityQuantity(point.production_2022_ktpa)) +
      optionalDetailCell("Proven + probable reserves", commodityQuantity(point.reserves_kt, "kt")) +
      optionalDetailCell("Total resources", commodityQuantity(point.resources_kt, "kt"))
    : "";
  const steelDetails = kind === "steel_plants"
    ? optionalDetailCell("Crude steel capacity", capacity) +
      optionalDetailCell("Iron capacity", commodityQuantity(point.iron_capacity_ktpa)) +
      optionalDetailCell("Blast-furnace capacity", commodityQuantity(point.bf_capacity_ktpa)) +
      optionalDetailCell("DRI capacity", commodityQuantity(point.dri_capacity_ktpa)) +
      optionalDetailCell("Pellet capacity", commodityQuantity(point.pellet_capacity_ktpa)) +
      optionalDetailCell("Coking capacity", commodityQuantity(point.coking_capacity_ktpa)) +
      optionalDetailCell("Main equipment", point.main_equipment) +
      optionalDetailCell("Power source", point.power_source) +
      optionalDetailCell("Iron ore source", point.iron_ore_source) +
      optionalDetailCell("Met coal source", point.met_coal_source) +
      optionalDetailCell("Steel products", point.product_type) +
      optionalDetailCell("End users", point.steel_end_users) +
      optionalDetailCell("Workforce", point.workforce_size)
    : "";
  const terminalDetails = kind === "iron_ore_terminals"
    ? optionalDetailCell("Trade direction", point.asset_type) +
      optionalDetailCell("Parent port", point.parent_port) +
      optionalDetailCell("Product", point.product_type) +
      optionalDetailCell("Evidence", point.evidence_level) +
      optionalDetailCell("Source review", point.source_date)
    : "";
  const note = kind === "iron_ore_mines"
    ? "Mine production, capacity, resources, ownership and location fields are from the GEM Global Iron Ore Mines Tracker. Unpublished values are omitted."
    : kind === "steel_plants"
      ? "Plant capacity, equipment, raw-material sourcing and ownership fields are from the GEM Global Iron and Steel Plant Tracker. Unpublished values are omitted."
      : point.coverage_note || "Major iron-ore terminal catalogue; not exhaustive.";
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">${escapeHtml(config.label)}</span>` +
    `<h2>${escapeHtml(point.name || config.label)}</h2>` +
    `<p class="detail-meta">${escapeHtml(point.country || "Country unknown")}</p>` +
    `<div class="detail-grid">` +
    optionalDetailCell("Status", point.status) +
    optionalDetailCell("Asset ID", point.id) +
    (kind === "steel_plants" ? "" : optionalDetailCell("Capacity", capacity)) +
    mineDetails + steelDetails + terminalDetails +
    optionalDetailCell("Owner", point.owner) +
    optionalDetailCell("Parent company", point.parent_company) +
    optionalDetailCell("Start date", point.start_date) +
    optionalDetailCell("Stop date", point.stop_date) +
    optionalDetailCell("Plant age", point.plant_age) +
    optionalDetailCell("Location", commodityLocation(point)) +
    optionalDetailCell("Coordinate accuracy", point.coordinate_accuracy) +
    optionalDetailCell("Coordinates", coordinates) +
    `</div>` +
    (sourceLink ? `<div class="detail-source-links">${sourceLink}</div>` : "") +
    `<p class="detail-note">${escapeHtml(note)}${point.source_text ? ` Source: ${escapeHtml(point.source_text)}${point.source_date ? ` (${escapeHtml(point.source_date)})` : ""}.` : ""}</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

function handlePortClick(port) {
  const voyageActive = document.querySelector(".voyage-section").open;
  if (!state.routeMode && !voyageActive) {
    showPortCard(port);
    return;
  }
  if (!state.routeMode) {
    state.routeMode = true;
    state.routePickIndex = 0;
  }
  state.routePorts[state.routePickIndex] = port;
  state.routePickIndex += 1;
  updateRouteSelection();
  if (state.routePickIndex >= 2) {
    state.routeMode = false;
    state.routePickIndex = 0;
    document.getElementById("route-pick").classList.remove("active");
    document.getElementById("route-pick").textContent = "Select two ports on map";
    renderPorts();
    calculateRoute();
  }
}

function routePortLabel(port) {
  return `${port.name}${port.country ? " · " + port.country : ""}`;
}

function populateRoutePortSearch() {
  document.getElementById("route-port-options").innerHTML = state.routePortCatalog.flatMap(port => [
    `<option value="${escapeAttr(routePortLabel(port))}"></option>`,
    ...(port.search_aliases || []).map(alias =>
      `<option value="${escapeAttr(alias)}">${escapeHtml(port.name)} · ${escapeHtml(port.country || "")}</option>`
    )
  ]).join("");
}

function normalizedPortQuery(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function routePortFromQuery(query) {
  const normalized = normalizedPortQuery(query);
  if (!normalized) return null;
  const exactLabel = state.routePortCatalog.find(port =>
    normalizedPortQuery(routePortLabel(port)) === normalized
  );
  if (exactLabel) return exactLabel;
  const exactName = state.routePortCatalog.find(port =>
    normalizedPortQuery(port.name) === normalized
  );
  if (exactName) return exactName;
  const exactAliasMatches = state.routePortCatalog.filter(port =>
    (port.search_aliases || []).some(alias =>
      normalizedPortQuery(alias) === normalized
    )
  );
  if (exactAliasMatches.length) {
    return exactAliasMatches.find(port => port.specialist_terminal)
      || exactAliasMatches[0];
  }
  return state.routePortCatalog.find(port =>
    normalizedPortQuery(port.name).startsWith(normalized)
  ) || state.routePortCatalog.find(port =>
    normalizedPortQuery(routePortLabel(port)).includes(normalized)
  ) || state.routePortCatalog.find(port =>
    (port.search_aliases || []).some(alias =>
      normalizedPortQuery(alias).includes(normalized)
    )
  ) || null;
}

function selectRoutePortFromInput(index, input) {
  const query = input.value.trim();
  if (!query) {
    clearRoutePort(index);
    return;
  }
  const port = routePortFromQuery(query);
  if (!port) {
    delete state.routePorts[index];
    state.routeLayer.clearLayers();
    document.getElementById(index === 0 ? "route-from-name" : "route-to-name").textContent =
      index === 0 ? "Select origin" : "Select destination";
    document.getElementById("route-result").textContent =
      "No matching port found. Continue typing or choose a port from the suggestions.";
    input.setCustomValidity("No matching port found. Choose a port from the suggestions.");
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  selectRoutePort(index, port.id);
}

function clearRoutePort(index) {
  delete state.routePorts[index];
  state.routeLayer.clearLayers();
  updateRouteSelection();
  renderPorts();
  document.getElementById("route-result").textContent =
    "Type both port names or select them directly on the map.";
}

function selectRoutePort(index, portId) {
  const port = state.routePortCatalog.find(item => String(item.id) === String(portId));
  if (port) state.routePorts[index] = port;
  else delete state.routePorts[index];
  state.routeMode = false;
  document.getElementById("route-pick").classList.remove("active");
  document.getElementById("route-pick").textContent = "Select two ports on map";
  updateRouteSelection();
  renderPorts();
  if (state.routePorts[0] && state.routePorts[1]) calculateRoute();
  else {
    state.routeLayer.clearLayers();
    document.getElementById("route-result").textContent =
      "Choose both ports or select them directly on the map.";
  }
}

function startRoutePicking() {
  state.routeMode = true;
  state.routePickIndex = 0;
  renderPorts();
  closePortCard();
  const button = document.getElementById("route-pick");
  button.classList.add("active");
  button.textContent = "Click origin port…";
  document.getElementById("route-result").textContent = "Click a port dot for the origin, then another for the destination.";
}

function updateRouteSelection() {
  const from = state.routePorts[0];
  const to = state.routePorts[1];
  const fromInput = document.getElementById("route-from-input");
  const toInput = document.getElementById("route-to-input");
  fromInput.value = from ? routePortLabel(from) : "";
  toInput.value = to ? routePortLabel(to) : "";
  fromInput.setCustomValidity("");
  toInput.setCustomValidity("");
  document.getElementById("route-from-name").textContent = from ? from.name : "Select origin";
  document.getElementById("route-to-name").textContent = to ? to.name : "Select destination";
  const button = document.getElementById("route-pick");
  if (state.routeMode) {
    button.textContent = state.routePickIndex === 0
      ? "Click origin port…"
      : "Click destination port…";
  }
}

function resetRoute(clearText = true) {
  state.routeLayer.clearLayers();
  state.routePorts = [];
  state.routeMode = false;
  state.routePickIndex = 0;
  const button = document.getElementById("route-pick");
  button.classList.remove("active");
  button.textContent = "Select two ports on map";
  updateRouteSelection();
  renderPorts();
  if (clearText) document.getElementById("route-result").textContent = "Click the button, then choose two port dots.";
}

function formatVoyageHours(value) {
  const hours = Math.max(0, Math.round(Number(value || 0)));
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

async function calculateRoute() {
  if (!state.routePorts[0] || !state.routePorts[1]) return;
  const [from, to] = state.routePorts;
  const speed = Number(document.getElementById("route-speed").value) || 12;
  const seaMargin = Number(document.getElementById("route-sea-margin").value) || 0;
  const portHours = Number(document.getElementById("route-port-hours").value) || 0;
  const canalHours = Number(document.getElementById("route-canal-hours").value) || 0;
  const avoid = Array.from(
    document.querySelectorAll(".route-restrictions input:checked")
  ).map(input => input.value);
  const result = document.getElementById("route-result");
  result.textContent = "Calculating sea route…";
  try {
    const response = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_lon: from.lon, from_lat: from.lat, to_lon: to.lon, to_lat: to.lat,
        from_port_id: String(from.id), to_port_id: String(to.id),
        speed_knots: speed, sea_margin_pct: seaMargin,
        port_time_hours: portHours, canal_delay_hours: canalHours,
        avoid,
        from_name: from.name, to_name: to.name
      })
    });
    const route = await response.json();
    if (!response.ok) throw new Error(route.detail || "Route calculation failed");
    const coordinates = (route.coordinates || []).map(item => [item[1], item[0]]);
    state.routeLayer.clearLayers();
    if (coordinates.length) {
      L.polyline(coordinates, { color: "#db2f34", weight: 3.2, opacity: 0.92 }).addTo(state.routeLayer);
      L.circleMarker(coordinates[0], { radius: 6, color: "#fff", weight: 2, fillColor: "#003671", fillOpacity: 1 }).addTo(state.routeLayer);
      L.circleMarker(coordinates[coordinates.length - 1], { radius: 6, color: "#fff", weight: 2, fillColor: "#db2f34", fillOpacity: 1 }).addTo(state.routeLayer);
      (route.route_ports || []).forEach((port, index) => {
        const marker = L.circleMarker([Number(port.lat), Number(port.lon)], {
          radius: 3,
          color: "#1c294a",
          weight: 0.8,
          opacity: 0.28,
          fillColor: "#ffffff",
          fillOpacity: 0.2
        }).addTo(state.routeLayer);
        marker.bindTooltip(
          escapeHtml(port.name || "Route port"),
          {
            className: "route-port-label",
            permanent: true,
            direction: index % 2 ? "bottom" : "top",
            offset: [0, index % 2 ? 5 : -5],
            opacity: 1
          }
        );
        marker.bindPopup(
          `<strong>${escapeHtml(port.name || "Route port")}</strong>` +
          `<br>${escapeHtml(port.country || "")}` +
          `<br>${formatNumber(port.distance_from_route_nm, 0)} nm from calculated track`
        );
      });
      state.map.fitBounds(coordinates, { padding: [50, 50] });
    }
    const nm = route.distance_nm != null ? route.distance_nm : route.distance_km / 1.852;
    const confidence = String(route.route_confidence || "estimated").toLowerCase();
    const confidenceLabel = route.routing_profile === "verified-approach-dense-corridor"
      ? "verified approaches"
      : `${confidence} confidence`;
    const alternate = route.alternate_cape_nm
      ? `<div><span>Alternative avoiding Suez</span><b>${formatNumber(route.alternate_cape_nm, 0)} nm · ${formatVoyageHours(Number(route.alternate_cape_days) * 24)}</b></div>`
      : "";
    const routePorts = (route.route_ports || []).length
      ? `<p class="route-port-summary"><b>Ports along the way</b><br>` +
        `${(route.route_ports || []).map(port =>
          `${escapeHtml(port.name || "Port")} (${formatNumber(port.distance_from_route_nm, 0)} nm)`
        ).join(" · ")}</p>`
      : "";
    result.innerHTML =
      `<div class="route-result-head"><div><span>Routed distance</span><strong>${formatNumber(nm, 0)} nm</strong></div>` +
      `<em class="route-confidence ${escapeAttr(confidence)}">${escapeHtml(confidenceLabel)}</em></div>` +
      `<div class="route-result-grid">` +
      `<div><span>Calm-sea time</span><b>${formatVoyageHours(route.calm_sea_hours)}</b></div>` +
      `<div><span>Total elapsed</span><b>${formatVoyageHours(route.total_duration_hours)}</b></div>` +
      `${alternate}</div>` +
      `<p><b>${escapeHtml(route.via ? "Via " + route.via : "Open-sea network route")}</b><br>` +
      `${formatNumber(speed, 1)} kn + ${formatNumber(route.sea_margin_pct, 1)}% sea margin` +
      `${Number(route.port_time_hours) ? ` + ${formatNumber(route.port_time_hours, 0)} hr port time` : ""}` +
      `${Number(route.canal_delay_hours) ? ` + ${formatNumber(route.canal_delay_hours, 0)} hr canal delay` : ""}</p>` +
      routePorts +
      `<small>${escapeHtml(route.coordinate_source || "Selected port coordinates")} · ` +
      `${Number(route.waypoint_count || 0).toLocaleString()} route points · analytical estimate, not for navigation.</small>`;
  } catch (error) {
    result.textContent = error.message;
  }
}

async function showPortCard(port) {
  const response = await fetch("/api/ports/" + encodeURIComponent(port.id));
  const detail = response.ok ? await response.json() : port;
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card");
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">Port</span><h2>${escapeHtml(detail.name)}</h2>` +
    `<p class="detail-meta">${escapeHtml(detail.country || "Country unknown")}${detail.unlocode ? " · " + escapeHtml(detail.unlocode) : ""}</p>` +
    `<div class="detail-grid">` +
    detailCell("Harbor size", detail.harbor_size) + detailCell("Harbor type", detail.harbor_type) +
    detailCell("Channel depth", detail.channel_depth) + detailCell("Cargo pier", detail.cargo_depth) +
    detailCell("Anchorage", detail.anchorage_depth) + detailCell("Max vessel", detail.max_vessel) +
    `</div><p class="detail-note">Berth count is unknown in the current source. Unknown values are not treated as zero.</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

function showAssetCard(config, point) {
  if (point.asset_kind === "coal_trade_terminals" && point.port_specification_available) {
    showCoalPortDetails(point);
    return;
  }
  if (
    point.asset_kind === "power_consumers" ||
    point.gem_location_id ||
    String(config.label || "").toLowerCase() === "coal plant"
  ) {
    showCoalPlantCard(config, point);
    return;
  }
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card");
  const sourceLink = point.source_url
    ? `<a class="detail-source-link" href="${escapeAttr(point.source_url)}" target="_blank" rel="noopener">Open source</a>`
    : "";
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">${escapeHtml(config.label)}</span><h2>${escapeHtml(point.name || config.label)}</h2>` +
    `<p class="detail-meta">${escapeHtml(point.country || "Country unknown")}</p>` +
    `<div class="detail-grid">` +
    detailCell("Status", point.status) +
    detailCell("Capacity", point.capacity == null ? "Unknown" : Number(point.capacity).toLocaleString() + " " + (point.capacity_unit || "MW")) +
    detailCell("Trade role", point.asset_type) +
    detailCell("Parent port", point.parent_port) +
    detailCell("Project status", point.project_status) +
    detailCell(
      "Expansion",
      point.expansion_capacity == null
        ? null
        : `+${Number(point.expansion_capacity).toLocaleString()} ${point.capacity_unit || "Mtpa"} · ${(point.expansion_status || []).join(" + ")}`
    ) +
    detailCell(
      "Potential capacity",
      point.potential_capacity == null
        ? null
        : `${Number(point.potential_capacity).toLocaleString()} ${point.capacity_unit || "Mtpa"}`
    ) +
    detailCell("Product", point.product_type) +
    detailCell("Supply source", point.source_text) +
    detailCell("Evidence", point.evidence_level) +
    detailCell("Source review", point.source_date) +
    `</div>${sourceLink}<p class="detail-note">${escapeHtml(point.coverage_note || "Source: Global Energy Monitor workbook layer.")}</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

function presentPlantValue(value) {
  if (value == null) return null;
  const text = String(value).trim();
  return text && !["nan", "null", "unknown"].includes(text.toLowerCase())
    ? text
    : null;
}

function finitePlantNumber(value) {
  return presentPlantValue(value) == null ? Number.NaN : Number(value);
}

function optionalDetailCell(label, value) {
  const displayed = presentPlantValue(value);
  return displayed ? detailCell(label, displayed) : "";
}

function plantCommissioning(point) {
  const start = Number(point.commissioning_start_year || point.unit_start_year);
  const end = Number(point.commissioning_end_year || point.unit_start_year);
  if (!Number.isFinite(start)) return null;
  return Number.isFinite(end) && end !== start ? `${start}–${end}` : String(start);
}

function showCoalPlantCard(config, point) {
  const card = document.getElementById("port-card");
  card.classList.remove("port-spec-card");
  const capacity = finitePlantNumber(point.plant_capacity ?? point.capacity);
  const unitCapacity = finitePlantNumber(point.capacity);
  const unitCount = finitePlantNumber(point.unit_count);
  const location = [
    presentPlantValue(point.location),
    presentPlantValue(point.district),
    presentPlantValue(point.state)
  ].filter(Boolean).join(" · ");
  const unitSummary = Number.isFinite(unitCount)
    ? `${unitCount.toLocaleString()} unit${unitCount === 1 ? "" : "s"}`
      + (Number.isFinite(unitCapacity) ? ` · selected unit ${unitCapacity.toLocaleString()} MW` : "")
    : presentPlantValue(point.unit);
  const factor = finitePlantNumber(point.capacity_factor);
  const co2 = finitePlantNumber(point.annual_co2_mtpa);
  const ceaSummary = point.cea_verified
    ? `${point.cea_unit_count} × ${Number(point.cea_capacity_mw / point.cea_unit_count).toLocaleString()} MW · commissioned ${point.cea_commissioning}`
    : null;
  const sourceLinks = [
    point.source_url
      ? `<a class="detail-source-link" href="${escapeAttr(point.source_url)}" target="_blank" rel="noopener">GEM plant record</a>`
      : "",
    point.cea_source_url
      ? `<a class="detail-source-link" href="${escapeAttr(point.cea_source_url)}" target="_blank" rel="noopener">CEA station register</a>`
      : "",
    point.npp_source_url
      ? `<a class="detail-source-link" href="${escapeAttr(point.npp_source_url)}" target="_blank" rel="noopener">NPP current reports</a>`
      : "",
    point.ministry_coal_source_url
      ? `<a class="detail-source-link" href="${escapeAttr(point.ministry_coal_source_url)}" target="_blank" rel="noopener">Coal-linkage records</a>`
      : ""
  ].filter(Boolean).join("");
  document.getElementById("port-card-content").innerHTML =
    `<span class="detail-eyebrow">${escapeHtml(config.label || "Coal-fired power plant")}</span>` +
    `<h2>${escapeHtml(point.name || "Coal-fired power plant")}</h2>` +
    `<p class="detail-meta">${escapeHtml(point.country || "Country unknown")}${point.state ? " · " + escapeHtml(point.state) : ""}</p>` +
    `<div class="detail-grid">` +
    optionalDetailCell("Status", point.status) +
    optionalDetailCell(
      "Plant capacity",
      Number.isFinite(capacity) ? `${capacity.toLocaleString()} MW` : null
    ) +
    optionalDetailCell("Unit configuration", unitSummary) +
    optionalDetailCell("Commissioned", plantCommissioning(point)) +
    optionalDetailCell("Owner", point.owner) +
    optionalDetailCell("Parent company", point.parent_company) +
    optionalDetailCell("Technology", point.combustion_technology) +
    optionalDetailCell("Coal type", point.coal_type) +
    optionalDetailCell("Coal source", point.coal_source) +
    optionalDetailCell("Captive industry use", point.captive_use) +
    optionalDetailCell("Location", location) +
    optionalDetailCell("Location accuracy", point.location_accuracy) +
    optionalDetailCell(
      "Capacity factor",
      Number.isFinite(factor) ? `${formatNumber(factor * 100, 1)}%` : null
    ) +
    optionalDetailCell(
      "Annual CO₂",
      Number.isFinite(co2) ? `${formatNumber(co2, 2)} Mt/year` : null
    ) +
    optionalDetailCell("CEA verification", ceaSummary) +
    optionalDetailCell(
      "CEA organisation / sector",
      point.cea_verified ? `${point.cea_organisation} · ${point.cea_sector}` : null
    ) +
    optionalDetailCell("Environmental permits", point.permits) +
    `</div>` +
    (sourceLinks ? `<div class="detail-source-links">${sourceLinks}</div>` : "") +
    `<p class="detail-note">${escapeHtml(
      point.cea_verified
        ? `CEA station details verified against the register dated ${point.cea_source_as_of}. Other technical, ownership and coal-supply fields are from the GEM plant record.`
        : point.coverage_note || "Plant attributes are from the Global Energy Monitor coal plant tracker."
    )}</p>`;
  card.classList.add("open");
  card.setAttribute("aria-hidden", "false");
}

async function showCoalPortDetails(point) {
  const card = document.getElementById("port-card");
  const content = document.getElementById("port-card-content");
  card.classList.add("port-spec-card", "open");
  card.setAttribute("aria-hidden", "false");
  content.innerHTML =
    `<span class="detail-eyebrow">India coal port</span>` +
    `<h2>${escapeHtml(point.name || "Port")}</h2>` +
    `<p class="detail-meta">Loading consolidated port specifications…</p>`;
  try {
    const response = await fetch(
      `/api/coal/port-specifications/${encodeURIComponent(point.id)}`
    );
    const detail = await response.json();
    if (!response.ok) throw new Error(detail.detail || "Port specifications are unavailable");
    const draft = detail.max_documented_draft_m == null
      ? "Not published"
      : `${formatNumber(detail.max_documented_draft_m, 1)} m`;
    const berthCount = detail.documented_berth_count == null
      ? "Not published"
      : formatNumber(detail.documented_berth_count, 0);
    const dryBulkCount = detail.documented_dry_bulk_berth_count == null
      ? "Not classified"
      : formatNumber(detail.documented_dry_bulk_berth_count, 0);
    const portCapacity = detail.port_capacity_mtpa == null
      ? "Not published"
      : `${formatNumber(detail.port_capacity_mtpa, 1)} MTPA`;
    const traffic = detail.latest_traffic_mt == null
      ? "Not available"
      : `${formatNumber(detail.latest_traffic_mt, 3)} MT`;
    const facilityRows = (detail.dry_bulk_facilities?.length
      ? detail.dry_bulk_facilities
      : detail.berth_facilities || []).slice(0, 14);
    const commodities = (detail.dry_bulk_commodities || []).slice(0, 8);
    const commodityFlows = (detail.commodity_flows || []).slice(0, 16);
    const sources = detail.sources || [];
    const lat = Number(detail.latitude);
    const lon = Number(detail.longitude);
    const satelliteViews = Number.isFinite(lat) && Number.isFinite(lon)
      ? (detail.satellite_context?.views || []).map(view =>
          `<figure><img loading="lazy" alt="${escapeAttr(`${view.label} satellite view of ${detail.asset_name}`)}" src="${escapeAttr(satelliteImageUrl(lat, lon, Number(view.span_degrees)))}">` +
          `<figcaption>${escapeHtml(view.label)}</figcaption></figure>`
        ).join("")
      : `<div class="coal-empty">Coordinates unavailable for satellite context.</div>`;
    content.innerHTML =
      `<span class="detail-eyebrow">India coal port</span>` +
      `<h2>${escapeHtml(detail.asset_name)}</h2>` +
      `<p class="detail-meta">${escapeHtml(detail.official_port_name || "Official port match unavailable")} · ${escapeHtml(detail.state_ut || "India")} · ${escapeHtml(detail.port_class || "Port class unavailable")}</p>` +
      `<div class="detail-grid port-spec-grid">` +
      detailCell("Max documented draft", draft) +
      detailCell("Documented berths", berthCount) +
      detailCell("Dry-bulk facilities", dryBulkCount) +
      detailCell("Port capacity", portCapacity) +
      detailCell("Latest port traffic", traffic) +
      detailCell("Traffic period", detail.latest_traffic_period) +
      detailCell("Terminal operating capacity", detail.terminal_operating_capacity_mtpa == null ? null : `${formatNumber(detail.terminal_operating_capacity_mtpa, 1)} MTPA`) +
      detailCell("Terminal expansion", detail.terminal_expansion_capacity_mtpa == null ? null : `+${formatNumber(detail.terminal_expansion_capacity_mtpa, 1)} MTPA`) +
      `</div>` +
      (detail.specification_note ? `<p class="port-spec-note">${escapeHtml(detail.specification_note)}</p>` : "") +
      `<section class="port-spec-section"><h3>Satellite context</h3><div class="satellite-grid">${satelliteViews}</div>` +
      `<small>Imagery: <a href="${escapeAttr(detail.satellite_context?.attribution_url || "https://www.arcgis.com/")}" target="_blank" rel="noopener noreferrer">Esri World Imagery</a>. Images provide geographic context and are not navigational charts.</small></section>` +
      `<section class="port-spec-section"><h3>Berths and terminal facilities</h3>` +
      (facilityRows.length
        ? `<ul class="facility-list">${facilityRows.map(item =>
            `<li><strong>${escapeHtml(item.name || "Documented facility")}</strong>` +
            `<span>${escapeHtml(formatFacilityPrimaryLine(item))}</span>` +
            (formatFacilitySecondaryLine(item)
              ? `<small>${escapeHtml(formatFacilitySecondaryLine(item))}</small>`
              : "") +
            (item.draft_conditions
              ? `<em>${escapeHtml(item.draft_conditions)}</em>`
              : "") +
            `</li>`
          ).join("")}</ul>`
        : `<div class="coal-empty">No berth-level specification was safely flattenable from the supplied workbook or current official source.</div>`) +
      (detail.berth_facilities?.length > facilityRows.length
        ? `<p class="port-spec-more">Showing ${facilityRows.length} dry-bulk-relevant records from ${detail.berth_facilities.length} documented berth/facility rows.</p>`
        : "") +
      `</section>` +
      (commodityFlows.length
        ? `<section class="port-spec-section"><h3>Coal flows by direction</h3><div class="commodity-chips">${commodityFlows.map(item =>
            `<span><strong>${escapeHtml(labelize(item.trade_direction || "reported flow"))}</strong>` +
            `${escapeHtml(labelize(item.commodity || "coal"))} · ${formatNumber(item.quantity_mt, 3)} MT · ${escapeHtml(item.period || "")}</span>`
          ).join("")}</div></section>`
        : "") +
      (commodities.length
        ? `<section class="port-spec-section"><h3>Latest documented dry-bulk flows</h3><div class="commodity-chips">${commodities.map(item =>
            `<span><strong>${escapeHtml(item.commodity)}</strong>${formatNumber(item.total_mt, 3)} MT · FY ${escapeHtml(item.fy || "")}</span>`
          ).join("")}</div></section>`
        : "") +
      `<section class="port-spec-section"><h3>Sources and verification</h3>` +
      (detail.official_website
        ? `<a class="official-port-link" href="${escapeAttr(detail.official_website)}" target="_blank" rel="noopener noreferrer">Open official port website ↗</a>`
        : "") +
      `<a class="official-port-link secondary" href="/api/coal/port-specifications/export">Download consolidated CSV</a>` +
      `<ul class="source-list">${sources.map(source =>
        `<li><a href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.title)}</a>` +
        `<span>${escapeHtml(source.scope || "")}${source.as_of ? ` · ${escapeHtml(String(source.as_of))}` : ""}</span></li>`
      ).join("")}</ul></section>` +
      `<p class="detail-note">${escapeHtml(detail.data_caveat || "Confirm current marine restrictions with the port or vessel agent.")}</p>`;
  } catch (error) {
    content.innerHTML =
      `<span class="detail-eyebrow">India coal port</span><h2>${escapeHtml(point.name || "Port")}</h2>` +
      `<p class="detail-note">${escapeHtml(error.message)}</p>`;
  }
}

function formatFacilityPrimaryLine(item) {
  const type = labelize(item.facility_type || "facility");
  const role = item.import_export_role && item.import_export_role !== "unknown"
    ? ` · ${labelize(item.import_export_role)}`
    : "";
  let draft = "Draft not published";
  if (item.draft_m != null) {
    if (item.facility_type === "anchorage") {
      draft = `${formatNumber(item.draft_m, 1)} m anchorage figure`;
    } else if (item.draft_type && item.draft_type !== "unknown") {
      draft = `${formatNumber(item.draft_m, 1)} m ${labelize(item.draft_type)} draft`;
    } else {
      draft = `${formatNumber(item.draft_m, 1)} m documented figure`;
    }
  }
  return `${type}${role} · ${draft} · as of ${item.as_of || "source date unavailable"}`;
}

function formatFacilitySecondaryLine(item) {
  const facts = [];
  if (item.quay_length_m != null) facts.push(`${formatNumber(item.quay_length_m, 0)} m quay`);
  if (item.max_dwt != null) facts.push(`${formatNumber(item.max_dwt, 0)} DWT`);
  if (item.annual_capacity_mtpa != null) facts.push(`${formatNumber(item.annual_capacity_mtpa, 1)} MTPA`);
  if (item.loading_rate_tph != null) facts.push(`${formatNumber(item.loading_rate_tph, 0)} TPH loading`);
  if (item.unloading_rate_tph != null) facts.push(`${formatNumber(item.unloading_rate_tph, 0)} TPH unloading`);
  if (item.handling_system) facts.push(item.handling_system);
  return facts.join(" · ");
}

function satelliteImageUrl(lat, lon, span) {
  const latitudeSpan = span * 0.7;
  const params = new URLSearchParams({
    bbox: `${lon - span},${lat - latitudeSpan},${lon + span},${lat + latitudeSpan}`,
    bboxSR: "4326",
    imageSR: "4326",
    size: "520,260",
    format: "jpg",
    f: "image"
  });
  return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?${params}`;
}

function closePortCard() {
  const card = document.getElementById("port-card");
  card.classList.remove("open");
  card.classList.remove("port-spec-card");
  card.classList.remove("weather-detail-card");
  card.classList.remove("river-detail-card");
  card.setAttribute("aria-hidden", "true");
}

function detailCell(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Unknown")}</strong></div>`;
}

function updateActiveCounts() {
  const energy = WORKSPACE_LAYERS.energy.filter(
    id => workspaceInput("energy", id)?.checked
  ).length;
  const commodities = WORKSPACE_LAYERS.commodities.filter(
    id => workspaceInput("commodities", id)?.checked
  ).length;
  document.getElementById("energy-active-count").textContent = `${energy} active`;
  document.getElementById("commodity-active-count").textContent = `${commodities} active`;
}

function updateMapStatus() {
  const ports = portsAllowedForMode() ? state.renderedPortCount : 0;
  let assets = 0;
  state.assetLayers.forEach(layer => {
    if (state.map.hasLayer(layer)) assets += Number(layer._pointCount || 0);
  });
  if (state.mode === "coal" && state.map.hasLayer(state.coalLayer)) {
    assets += Number(state.coalLayer._pointCount || 0);
  }
  const parts = [];
  if (ports) parts.push(`${ports.toLocaleString()} ports`);
  if (assets) parts.push(`${assets.toLocaleString()} assets`);
  if (state.aisEnabled && state.aisVessels.length) {
    parts.push(`${displayedAisVessels().length.toLocaleString()} AIS vessels`);
  }
  setStatus(parts.length ? parts.join(" · ") : "No layers selected");
}

function setStatus(text) {
  document.getElementById("map-status").textContent = text;
}

function setLoading(active, text = "Loading layer…") {
  const indicator = document.getElementById("loading-indicator");
  indicator.hidden = !active;
  indicator.textContent = text;
}

function labelize(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
