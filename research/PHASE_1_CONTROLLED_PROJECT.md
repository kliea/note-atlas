# Phase 1 — Controlled test project

**Fixture path:** `sca-experiment/`  
**Ground truth:** [GROUND_TRUTH.md](GROUND_TRUTH.md)  
**Realism template:** [../baseline/REAL_PROJECT_PROFILE.md](../baseline/REAL_PROJECT_PROFILE.md)

## Intent

Build a *plausible* Note Atlas-shaped app whose **declared and locked dependencies are the experiment**, not the product. Known-vulnerable versions are planted on purpose so scanner recall/precision has an answer key.

## What was mirrored from Phase 0

| Real project | Controlled fixture |
| --- | --- |
| FastAPI + uvicorn + pydantic + httpx + pytest | Same categories; **not Django** |
| `sentence-transformers` / `transformers` ML tree | `sentence-transformers` range + pinned old `transformers` |
| `sqlite-vec` | Declared, range-style |
| Jinja2 / idna / urllib3 / anyio / h11 as real transitive categories | Planted as **direct pins** so they cannot float away |
| React + Vite + TypeScript + pnpm + `@xyflow/react` | Same; Vite 5-era pins (old enough to carry published CVEs) |
| Python **unlocked** vs Node **locked** | Preserved: `requirements.txt` has no lockfile; frontend has `pnpm-lock.yaml` |

## Lockfile contrast (experimental variable)

- **Python:** unpinned-style file (mix of `==` planted pins and `>=` / `<` ranges). No `poetry.lock` / `uv.lock` / pip-tools compile.
- **Node:** exact versions in `package.json` plus `overrides` in `pnpm-workspace.yaml` (pnpm 10+ does not read `package.json#pnpm.overrides`), and a committed `pnpm-lock.yaml`.

That contrast is intentional. A later phase can ask whether scanners and SBOMs treat the two ecosystems differently.

## What this fixture is not

- Not a copy of Note Atlas source.
- Not an exploit lab. CVEs are **declared for detection**, not demonstrated.
- Not a complete inventory of every transitive advisory (especially `torch` pulled by the ML stack). Only **planted directs** are ground truth.

## Layout

```
sca-experiment/
  backend/          FastAPI app + requirements.txt (no lockfile)
  frontend/         React + Vite + pnpm-lock.yaml
research/
  GROUND_TRUTH.md   Expected CVE table
```
