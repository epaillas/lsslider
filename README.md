# Galaxy Clustering Slider

Local interactive demo for galaxy power spectrum multipoles built on top of `desilike`.

## Architecture

- Backend: `FastAPI` + `uvicorn`
- Frontend: `React` + `TypeScript` + `Vite`
- Plotting: `Plotly.js`
- Theory engine: `desilike`

The backend reuses the local `desilike` theory layer in [lsslider/theory.py](/Users/epaillas/code/lsslider/lsslider/theory.py). The frontend source lives in [frontend/src/App.tsx](/Users/epaillas/code/lsslider/frontend/src/App.tsx) and builds into [lsslider/static](/Users/epaillas/code/lsslider/lsslider/static).

## Current scope

- Theory models:
  - `FOLPSv2`
  - `REPT Velocileptors`
- Parameter categories:
  - `Cosmology`
  - `Bias`
  - `Counterterms`
  - `Stochastic / FoG`
- Observable:
  - stacked `k P_ell(k)` for `ell = 0, 2, 4`
- Fixed setup:
  - tracer: `LRG`
  - redshift: `z = 0.5`
  - `0.01 <= k <= 0.2`
- Backends:
  - `direct`
  - `emulated` with on-demand cached Taylor emulators under `.cache/emulators/`

## Run

For production-style local serving:

```bash
python -m lsslider --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Frontend Development

Run the backend:

```bash
python -m lsslider --host 127.0.0.1 --port 8000 --reload
```

In a second terminal, run the Vite dev server:

```bash
cd frontend
npm run dev
```

Then open:

```text
http://127.0.0.1:5173
```

## Build Frontend

```bash
cd frontend
npm run build
```

This writes the compiled assets into `lsslider/static/`, which FastAPI serves directly.

## Deploy

This repo includes a `Dockerfile` and `render.yaml` for Render deployment.

- Service name: `lsslider`
- Expected public URL: `https://lsslider.onrender.com`
- Health check: `/api/health`

For local parity with the hosted environment, the app now reads `HOST` and `PORT` from the environment when those variables are set.

## Notes

- The first `emulated` request can take several seconds while the emulator is built and cached.
- Direct mode is still the default because the current parameter space is narrow enough for local exploration.
- The compiled Plotly bundle is large; if startup payload becomes a problem, the next step is code-splitting or a lighter plotting layer.
