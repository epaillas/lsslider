import { useEffect, useMemo, useRef, useState } from "react";

type ParamSpec = {
  name: string;
  label: string;
  category: string;
  value: number;
  min: number;
  max: number;
  step: number;
};

type ModelConfig = {
  key: string;
  label: string;
  defaults: Record<string, number>;
  parameter_groups: Record<string, ParamSpec[]>;
  plot_limits: Record<string, Record<string, { min: number; max: number }>>;
};

type AppConfig = {
  app: {
    title: string;
    subtitle: string;
    default_model: string;
    default_backend: string;
    category_labels: Record<string, string>;
    category_order: Record<string, number>;
  };
  setup: {
    tracer: string;
    z: number;
    ells: number[];
    k_min: number;
    k_max: number;
    dk: number;
    n_k: number;
  };
  models: ModelConfig[];
  backends: { key: string; label: string }[];
};

type EvaluateResponse = {
  model: string;
  backend: string;
  elapsed_ms: number;
  k: number[];
  ells: number[];
  poles: Record<string, number[]>;
  values: Record<string, number>;
};

const EMPTY_PLOT: EvaluateResponse | null = null;
const CHART_WIDTH = 920;
const CHART_PADDING = { top: 20, right: 20, bottom: 52, left: 118 };
const PANEL_HEIGHT = 175;
const PANEL_GAP = 18;
const MULTIPOLE_COLORS: Record<number, string> = {
  0: "#005f73",
  2: "#bb3e03",
  4: "#6c584c",
};

function formatNumber(value: number): string {
  const absValue = Math.abs(value);
  if (absValue === 0) return "0";
  if (absValue >= 1e4 || absValue < 1e-3) return value.toExponential(3);
  if (absValue >= 100) return value.toFixed(1);
  if (absValue >= 1) return value.toFixed(3);
  return value.toFixed(5);
}

function scaledPoles(plot: EvaluateResponse | null): { ell: number; y: number[] }[] {
  if (!plot) return [];
  return plot.ells.map((ell) => ({
    ell,
    y: plot.poles[String(ell)].map((value, index) => value * plot.k[index]),
  }));
}

function tickValues(min: number, max: number, count: number): number[] {
  if (count <= 1 || max === min) return [min];
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

function buildLinePath(points: Array<{ x: number; y: number }>): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
}

function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [modelKey, setModelKey] = useState<string>("");
  const [backendKey, setBackendKey] = useState<string>("");
  const [categoryKey, setCategoryKey] = useState<string>("");
  const [params, setParams] = useState<Record<string, number>>({});
  const [plot, setPlot] = useState<EvaluateResponse | null>(EMPTY_PLOT);
  const [status, setStatus] = useState<string>("Loading configuration…");
  const [timing, setTiming] = useState<string>("");
  const requestId = useRef(0);
  const debounceRef = useRef<number | null>(null);

  const models = config?.models ?? [];
  const model = useMemo(() => models.find((item) => item.key === modelKey) ?? null, [models, modelKey]);
  const categoryEntries = useMemo(() => {
    if (!config || !model) return [];
    return Object.entries(config.app.category_labels)
      .filter(([key]) => (model.parameter_groups[key] ?? []).length > 0)
      .sort((a, b) => config.app.category_order[a[0]] - config.app.category_order[b[0]])
      .map(([key, label]) => ({ key, label }));
  }, [config, model]);
  const visibleSpecs = useMemo(() => model?.parameter_groups[categoryKey] ?? [], [model, categoryKey]);

  useEffect(() => {
    async function loadConfig() {
      const response = await fetch("/api/config");
      const payload = (await response.json()) as AppConfig;
      setConfig(payload);
      setModelKey(payload.app.default_model);
      setBackendKey(payload.app.default_backend);
      const nextModel = payload.models.find((item) => item.key === payload.app.default_model)!;
      setParams({ ...nextModel.defaults });
      const firstCategory = Object.entries(payload.app.category_labels)
        .filter(([key]) => (nextModel.parameter_groups[key] ?? []).length > 0)
        .sort((a, b) => payload.app.category_order[a[0]] - payload.app.category_order[b[0]])[0]?.[0];
      setCategoryKey(firstCategory ?? "");
    }
    void loadConfig().catch((error: Error) => {
      setStatus(`Failed to initialize: ${error.message}`);
    });
  }, []);

  useEffect(() => {
    if (!config || !model) return;
    if (!categoryEntries.some((entry) => entry.key === categoryKey)) {
      setCategoryKey(categoryEntries[0]?.key ?? "");
    }
  }, [config, model, categoryEntries, categoryKey]);

  const scheduleEvaluate = (nextModelKey: string, nextBackendKey: string, nextParams: Record<string, number>) => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      void evaluate(nextModelKey, nextBackendKey, nextParams).catch((error: Error) => {
        setStatus(`Error: ${error.message}`);
      });
    }, 80);
  };

  const evaluate = async (nextModelKey: string, nextBackendKey: string, nextParams: Record<string, number>) => {
    const currentRequestId = ++requestId.current;
    setStatus(nextBackendKey === "emulated" ? "Evaluating or building emulator…" : "Evaluating theory…");
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: nextModelKey, backend: nextBackendKey, params: nextParams }),
    });
    const payload = (await response.json()) as EvaluateResponse | { detail?: string };
    if (!response.ok) {
      throw new Error("detail" in payload ? payload.detail ?? "Request failed" : "Request failed");
    }
    if (currentRequestId !== requestId.current) return;
    setPlot(payload as EvaluateResponse);
    setStatus("Ready");
    setTiming(`${(payload as EvaluateResponse).elapsed_ms.toFixed(1)} ms`);
  };

  useEffect(() => {
    if (!config || !modelKey || !backendKey || !Object.keys(params).length) return;
    scheduleEvaluate(modelKey, backendKey, params);
    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [config, modelKey, backendKey, params]);

  const onModelChange = (nextModelKey: string) => {
    if (!config) return;
    const nextModel = config.models.find((item) => item.key === nextModelKey);
    if (!nextModel) return;
    setModelKey(nextModelKey);
    setParams({ ...nextModel.defaults });
    const firstCategory = Object.entries(config.app.category_labels)
      .filter(([key]) => (nextModel.parameter_groups[key] ?? []).length > 0)
      .sort((a, b) => config.app.category_order[a[0]] - config.app.category_order[b[0]])[0]?.[0];
    setCategoryKey(firstCategory ?? "");
  };

  const chartPanels = useMemo(() => {
    if (!plot || !model) return [];
    const xMin = plot.k[0];
    const xMax = plot.k[plot.k.length - 1];
    const plotWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const xScale = (value: number) => CHART_PADDING.left + ((value - xMin) / (xMax - xMin)) * plotWidth;
    const referenceLimits = model.plot_limits.cosmology ?? model.plot_limits[categoryKey] ?? {};
    return scaledPoles(plot).map((panel, index) => {
      const panelTop = CHART_PADDING.top + index * (PANEL_HEIGHT + PANEL_GAP);
      const bounds = referenceLimits[String(panel.ell)] ?? model.plot_limits[categoryKey]?.[String(panel.ell)];
      const yMin = bounds?.min ?? Math.min(...panel.y);
      const yMax = bounds?.max ?? Math.max(...panel.y);
      const ySpan = Math.max(yMax - yMin, 1e-8);
      const yScale = (value: number) => panelTop + PANEL_HEIGHT - ((value - yMin) / ySpan) * PANEL_HEIGHT;
      const ticksY = tickValues(yMin, yMax, 5);
      const points = plot.k.map((kValue, pointIndex) => ({ x: xScale(kValue), y: yScale(panel.y[pointIndex]) }));
      return {
        ell: panel.ell,
        panelTop,
        panelBottom: panelTop + PANEL_HEIGHT,
        ticksY,
        yScale,
        path: buildLinePath(points),
        color: MULTIPOLE_COLORS[panel.ell] ?? "#005f73",
      };
    });
  }, [plot, model, categoryKey]);

  const chartHeight = useMemo(() => {
    if (!plot) return 640;
    return CHART_PADDING.top + CHART_PADDING.bottom + plot.ells.length * PANEL_HEIGHT + (plot.ells.length - 1) * PANEL_GAP;
  }, [plot]);

  const xTicks = useMemo(() => {
    if (!plot) return [];
    const tickIndices = [0, Math.floor(plot.k.length / 3), Math.floor((2 * plot.k.length) / 3), plot.k.length - 1];
    return tickIndices.map((index) => plot.k[index]);
  }, [plot]);

  if (!config || !model) {
    return <div className="boot-state">{status}</div>;
  }

  return (
    <div className="app-shell">
      <header className="masthead">
        <div className="masthead-copy">
          <p className="eyebrow">{config.app.title}</p>
          <h1>Interactive perturbation theory multipoles</h1>
          <p className="lede">{config.app.subtitle}</p>
        </div>
        <div className="setup-strip setup-controls">
          <label className="field compact-field">
            <span>Theory model</span>
            <select value={modelKey} onChange={(event) => onModelChange(event.target.value)}>
              {config.models.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field compact-field">
            <span>Backend</span>
            <select value={backendKey} onChange={(event) => setBackendKey(event.target.value)}>
              {config.backends.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field compact-field">
            <span>Parameter category</span>
            <select value={categoryKey} onChange={(event) => setCategoryKey(event.target.value)}>
              {categoryEntries.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>

        </div>
      </header>

      <div className="workspace">
        <main className="plot-pane">
          <div className="plot-header">
            <div>
              <p className="eyebrow">Observable</p>
              <h2>Galaxy power spectrum multipoles</h2>
            </div>
            <div className="plot-meta">
              <span className="legend-item">Current model</span>
              <span className={`status-badge ${status === "Ready" ? "status-ready" : ""}`}>{status}</span>
              <span className="timing-badge">{timing || "…"}</span>
            </div>
          </div>

          <section className="plot-card">
            <div className="plot-frame">
              {plot ? (
                <svg
                  className="plot-svg"
                  viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`}
                  role="img"
                  aria-label="Galaxy power spectrum multipoles"
                >
                  <defs>
                    {chartPanels.map((panel) => (
                      <clipPath key={`clip-${panel.ell}`} id={`panel-clip-${panel.ell}`}>
                        <rect
                          x={CHART_PADDING.left}
                          y={panel.panelTop}
                          width={CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right}
                          height={PANEL_HEIGHT}
                        />
                      </clipPath>
                    ))}
                  </defs>
                  {chartPanels.map((panel, index) => (
                    <g key={panel.ell}>
                      {panel.ticksY.map((tick) => {
                        const y = panel.yScale(tick);
                        return (
                          <g key={`${panel.ell}-${tick}`}>
                            <line
                              className="plot-grid-line"
                              x1={CHART_PADDING.left}
                              x2={CHART_WIDTH - CHART_PADDING.right}
                              y1={y}
                              y2={y}
                            />
                            <text className="plot-tick-label" x={CHART_PADDING.left - 10} y={y + 4} textAnchor="end">
                              {formatNumber(tick)}
                            </text>
                          </g>
                        );
                      })}
                      <line
                        className="plot-axis-line"
                        x1={CHART_PADDING.left}
                        x2={CHART_PADDING.left}
                        y1={panel.panelTop}
                        y2={panel.panelBottom}
                      />
                      {index === chartPanels.length - 1 ? (
                        <line
                          className="plot-axis-line"
                          x1={CHART_PADDING.left}
                          x2={CHART_WIDTH - CHART_PADDING.right}
                          y1={panel.panelBottom}
                          y2={panel.panelBottom}
                        />
                      ) : null}
                      <text className="plot-panel-title" x={CHART_PADDING.left + 8} y={panel.panelTop + 16}>
                        {`ell = ${panel.ell}`}
                      </text>
                      <text
                        className="plot-axis-label plot-axis-label-y"
                        x={36}
                        y={(panel.panelTop + panel.panelBottom) / 2}
                        textAnchor="middle"
                        transform={`rotate(-90 36 ${(panel.panelTop + panel.panelBottom) / 2})`}
                      >
                        {`k P${panel.ell}(k) [(Mpc/h)^2]`}
                      </text>
                      <path
                        className="plot-line"
                        d={panel.path}
                        style={{ stroke: panel.color }}
                        clipPath={`url(#panel-clip-${panel.ell})`}
                      />
                    </g>
                  ))}

                  {xTicks.map((tick) => {
                    const x =
                      CHART_PADDING.left +
                      ((tick - plot.k[0]) / (plot.k[plot.k.length - 1] - plot.k[0])) *
                        (CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right);
                    return (
                      <text
                        key={`x-${tick}`}
                        className="plot-tick-label"
                        x={x}
                        y={chartHeight - 16}
                        textAnchor="middle"
                      >
                        {tick.toFixed(3)}
                      </text>
                    );
                  })}
                  <text className="plot-axis-label" x={CHART_WIDTH / 2} y={chartHeight - 2} textAnchor="middle">
                    k [h Mpc^-1]
                  </text>
                </svg>
              ) : (
                <div className="plot-loading">Loading plot…</div>
              )}
            </div>
          </section>
        </main>

        <aside className="control-rail">
          <section className="slider-card-panel">
            <div className="section-heading">
              <div className="section-heading-row">
                <h2>Parameters</h2>
                <button
                  className="reset-button reset-button-inline"
                  type="button"
                  onClick={() => setParams({ ...model.defaults })}
                >
                  Reset
                </button>
              </div>
              <p>{config.app.category_labels[categoryKey]} parameters for the current model.</p>
            </div>

            <div className="slider-list">
              {visibleSpecs.map((spec) => (
                <article className="slider-card" key={spec.name}>
                  <div className="slider-card-top">
                    <span className="slider-name">{spec.label}</span>
                    <span className="slider-value">{formatNumber(params[spec.name])}</span>
                  </div>
                  <input
                    type="range"
                    min={spec.min}
                    max={spec.max}
                    step={spec.step}
                    value={params[spec.name]}
                    onChange={(event) => {
                      const nextValue = Number(event.target.value);
                      setParams((current) => ({ ...current, [spec.name]: nextValue }));
                    }}
                  />
                  <div className="slider-range">
                    <span>{formatNumber(spec.min)}</span>
                    <span>{formatNumber(spec.max)}</span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

export default App;
