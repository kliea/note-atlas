# Real-project dependency profile — Note Atlas

Read-only baseline of `/Users/klinthjeraldmatugas/Documents/DEV/ATLAS` on 2026-09-21. No application code, dependency pins, or lockfiles were modified. This profile is only the technical/dependency shape of the repo, for making a controlled supply-chain experiment realistic.

**Project (public description):** local-first spatial notebook. FastAPI talks to a local Ollama process; the UI is a React canvas. Nothing in this summary is proprietary source.

---

## 1. Stack and manifests

| Layer | Stack | Manifest | Lockfile |
| --- | --- | --- | --- |
| Backend | Python 3.12 (venv at `backend/.venv`) | `backend/requirements.txt` (unpinned lower bounds, `>=`) | **None** (no `poetry.lock` / `uv.lock` / pip-tools compile) |
| Frontend | Node.js + **pnpm** 9 lockfile, React 19, Vite 6, TypeScript 5 | `frontend/package.json` | `frontend/pnpm-lock.yaml` (`lockfileVersion: '9.0'`) |
| Runtime (not a package) | Ollama HTTP API on loopback | `.env.example` (`OLLAMA_HOST`, `OLLAMA_MODEL`) | n/a |

**Ecosystems in use:** PyPI and npm (via pnpm). No Go, Rust, Java, Ruby, PHP, or .NET manifests.

**Package managers:** `pip` + venv (backend); `pnpm` (frontend). `frontend/pnpm-workspace.yaml` is a single-package workspace (`packages: ['.']`).

**SBOM:** CycloneDX 1.6 JSON at `baseline/sbom-real.json` (merge of `cyclonedx-py environment` on the backend venv, 53 components, and `@cyclonedx/cdxgen` on the pnpm lockfile, 139 components). Per-ecosystem sources: `baseline/sbom-python.json`, `baseline/sbom-node.json`.

---

## 2. Dependency counts (direct vs resolved)

### Python (PyPI)

| Metric | Count | Source |
| --- | --- | --- |
| Direct declared | **7** | `backend/requirements.txt` |
| Resolved installed (`pip list`) | **53** | venv site-packages, includes `pip` + `setuptools` |
| Resolved (`pip freeze`) | **52** | same, excludes `pip` |
| SBOM components | **53** | `cyclonedx-py environment` |
| Transitive (resolved − direct, incl. bootstrap) | **46** | 53 − 7 |
| Application resolved excluding `pip`/`setuptools` | **51** | 53 − 2 |
| Application transitive excluding bootstrap | **44** | 51 − 7 |

Direct names: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `pytest`, `sentence-transformers`, `sqlite-vec`.

Installed versions of those directs: FastAPI 0.141.1, uvicorn 0.53.0, pydantic 2.13.5, httpx 0.28.1, pytest 9.1.1, sentence-transformers 6.0.1, sqlite-vec 0.1.9.

The Python tree is **ML-heavy**: `sentence-transformers` pulls `torch` 2.14.0, `transformers` 5.17.0, `tokenizers`, `huggingface-hub`, `numpy`, `scipy`, `scikit-learn`. The web slice is small (`starlette`, `anyio`, `h11`, `httpcore`).

**Supply-chain note for the experiment:** backend deps are range-pinned only. A controlled clone should either keep that (reproducible-resolution risk) or add a lockfile to contrast with the frontend.

### Node (npm registry, pnpm)

| Metric | Count | Source |
| --- | --- | --- |
| Direct runtime | **3** | `package.json` `dependencies` |
| Direct dev | **5** | `package.json` `devDependencies` |
| Direct total | **8** | 3 + 5 |
| Unique `name@version` in lockfile (peer suffixes stripped) | **93** | `pnpm-lock.yaml` `packages:` |
| Resolved including optional native binaries | **139** | `pnpm audit` `totalDependencies`; cdxgen component count |
| Optional platform packages (`@esbuild/*`, `@rollup/rollup-*`, `@napi-rs/*`) | **~52** | lockfile / SBOM |
| Logical unique names excluding those platform packages | **~41** | lockfile names minus native optional |
| Transitive (139 − 8) | **131** | includes unused-OS optional binaries |
| Transitive logical (~41 − 8) | **~33** | better “what a developer thinks they depend on” |

Direct runtime: `react`, `react-dom`, `@xyflow/react`.  
Direct dev: `typescript`, `vite`, `@vitejs/plugin-react`, `@types/react`, `@types/react-dom`.

Resolved versions of directs: React 19.3.0, `@xyflow/react` 12.11.6, Vite 6.4.3, TypeScript 5.9.3, `@vitejs/plugin-react` 4.7.0.

`pnpm audit` metadata split: 26 production, 113 development, 53 optional, 139 total.

**Supply-chain note for the experiment:** frontend is locked; a large share of “resolved” count is **optional native binaries** for esbuild/rollup, not JS libraries. Mirror that if the experiment cares about lockfile cardinality vs logical graph size.

---

## 3. Package categories present

Use these categories when picking packages for the controlled project. Names only; no application logic.

### Python — present

| Category | How it shows up |
| --- | --- |
| Web framework | `fastapi` → `starlette` |
| ASGI / HTTP server | `uvicorn` |
| HTTP client | `httpx` (declared); stdlib `urllib` also used for the local LLM |
| Validation / schema | `pydantic`, `pydantic-core`, `annotated-types` |
| Testing | `pytest`, `pluggy`, `iniconfig` |
| Embeddings / NLP / ML | `sentence-transformers`, `transformers`, `tokenizers`, `torch`, `huggingface-hub`, `safetensors` |
| Numeric / scientific | `numpy`, `scipy`, `scikit-learn`, `joblib`, `threadpoolctl` |
| Vector store / DB | `sqlite-vec` (SQLite extension; app SQLite is stdlib) |
| Templating | `Jinja2` (transitive, via ML stack) |
| YAML / config parsing | `PyYAML` (transitive) |
| TLS / identity | `certifi`, `idna` |
| CLI / console (transitive) | `typer`, `rich`, `click` via Hugging Face tooling |
| Async primitives | `anyio`, `h11`, `httpcore` |

### Node — present

| Category | How it shows up |
| --- | --- |
| UI framework | `react`, `react-dom`, `scheduler` |
| Graph / canvas / spatial UI | `@xyflow/react`, `@xyflow/system` |
| Pointer / zoom interaction | `d3-drag`, `d3-zoom`, `d3-selection`, `d3-interpolate`, `d3-transition`, … |
| Client state | `zustand`, `use-sync-external-store` |
| Bundler / dev server | `vite`, `esbuild`, `rollup`, `@vitejs/plugin-react` |
| Transpiler | `@babel/*` |
| Language / types | `typescript`, `@types/react`, `@types/react-dom` |
| CSS tooling (minimal) | `postcss`, `nanoid`, `source-map-js` (via Vite, not a CSS framework) |

### Frontend HTTP

Browser `fetch` to the local API. **No** `axios` / `node-fetch` / `ky` direct dependency.

### Not present (do not invent these unless the experiment needs a contrast)

- Auth / identity (`oauth`, JWT, session, Passport, FastAPI-Users)
- Image handling (`Pillow`, `sharp`, `imageio`)
- ORM / SQL toolkit (`SQLAlchemy`, `prisma`, `drizzle`)
- Cloud SDKs (`boto3`, Firebase, Stripe)
- CSS frameworks (`tailwind`, `styled-components`)
- Express / Next.js / Django / Flask
- Redis, Postgres drivers, message queues

### External runtime, not a lockfile package

- **Ollama** (local LLM). Treat as an optional runtime service in the experiment, not a PyPI/npm component.

---

## 4. Headline vulnerability counts (one scanner per ecosystem)

Scans were read-only against the **installed** backend venv and the **pnpm lockfile**. Raw output is in `baseline/`.

| Ecosystem | Scanner | Result |
| --- | --- | --- |
| Python | `pip-audit` 2.10.1, `--path backend/.venv/lib/python3.12/site-packages`, PyPI advisory service | **2 findings in 1 package** (`pip` 26.1.2). Unique advisory: **PYSEC-2026-3721** / **CVE-2026-13346** (listed twice with fix versions `26.2` and `26.2.0`). **0 findings** in the 7 direct application packages and the rest of the app/ML tree. |
| Node | `pnpm audit` (npm advisory database; correct scanner for this lockfile) | **0** (info/low/moderate/high/critical all 0). Text: `No known vulnerabilities found`. |
| Node (as requested) | `npm audit` | **Did not run.** Exit `ENOLOCK` — this repo has `pnpm-lock.yaml`, not `package-lock.json`. Raw error: `baseline/npm-audit.json`, `baseline/npm-audit.txt`. |

Files:

- `baseline/pip-audit.json` / `baseline/pip-audit.txt`
- `baseline/pnpm-audit.json` / `baseline/pnpm-audit.txt`
- `baseline/npm-audit.json` / `baseline/npm-audit.txt` (failure only)

`pip` is the venv bootstrap installer, not a declared app dependency. For an application-only headline: **0 known vulns in declared Python deps; 0 in the Node graph.** Including the environment: **2 pip-audit findings (1 unique CVE) + 0 npm advisories.**

---

## 5. What to mirror in the controlled test project

1. **Two ecosystems:** PyPI app with unpinned `requirements.txt`, and a small npm/pnpm React app with a lockfile.
2. **Python category mix:** web framework + ASGI + HTTP client + pydantic + pytest, plus at least one **ML/embeddings** package if the experiment should reproduce a large transitive tree (`torch`/`transformers`-class). If the experiment only needs “web + HTTP”, the logical app surface is 4–5 packages; the *real* resolved count is dominated by ML.
3. **Node category mix:** React UI + a canvas/graph library (`@xyflow/*` / React Flow class) + Vite/TypeScript toolchain. Expect optional native binary fan-out in the lockfile.
4. **Do not add** auth, image, ORM, or cloud SDKs if the goal is realism against this repo.
5. **Lockfile contrast:** Python unlocked vs Node locked is itself a realistic supply-chain difference.
6. **SBOM target size:** ~50 PyPI components + ~40 logical npm packages (or ~140 if optional natives are in scope), CycloneDX 1.6.

---

## 6. Method (reproducibility)

- Python resolved set: `backend/.venv/bin/python -m pip list` / `pip freeze` (existing venv; not reinstalled).
- Node resolved set: `frontend/pnpm-lock.yaml` + `pnpm audit` metadata + cdxgen 11.6.0.
- Python SBOM: `cyclonedx-py environment backend/.venv` (cyclonedx-bom 7.4.0).
- Node SBOM: `npx @cyclonedx/cdxgen@11.6.0 --type pnpm`.
- Merge: components concatenated; root component `note-atlas` with backend/frontend children → `baseline/sbom-real.json`.
- Tools were installed in a throwaway `/tmp` venv, not in `backend/.venv`.
