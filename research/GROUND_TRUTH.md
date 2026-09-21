# Ground truth — planted vulnerable dependencies

Answer key for `sca-experiment/`. Only **directly planted** pins are ground truth. Scanners may also report aliases (GHSA/PYSEC), extra CVEs on the same pin, or **transitive** findings (especially `torch` via `sentence-transformers` / `transformers`). Those extras are confounders, not failures of this table.

Versions were checked against [OSV](https://osv.dev) on 2026-09-21. **Do not upgrade these pins.**

Realism template: [../baseline/REAL_PROJECT_PROFILE.md](../baseline/REAL_PROJECT_PROFILE.md).

## Python (PyPI) — 12 planted pins

Manifest: `sca-experiment/backend/requirements.txt` (no lockfile). Range-style lines (`uvicorn`, `sentence-transformers`, `sqlite-vec`) are **not** ground truth.

| Package | Ecosystem | Pinned version | Known CVE(s) | Severity | Category | Mirrors-real-category |
| --- | --- | --- | --- | --- | --- | --- |
| fastapi | PyPI | 0.109.0 | CVE-2024-24762 | High | Web framework | fastapi |
| starlette | PyPI | 0.36.1 | CVE-2024-47874, CVE-2025-54121 | High, Moderate | Web framework (ASGI kit) | starlette via fastapi |
| python-multipart | PyPI | 0.0.6 | CVE-2024-24762, CVE-2024-53981 | High | Form / multipart parsing | FastAPI form stack |
| httpx | PyPI | 0.19.0 | CVE-2021-41945 | Moderate | HTTP client | httpx |
| pydantic | PyPI | 1.10.4 | CVE-2024-3772 | Moderate | Validation / schema | pydantic |
| pytest | PyPI | 8.3.4 | CVE-2025-71176 | Moderate | Testing | pytest |
| transformers | PyPI | 4.36.2 | CVE-2024-3568, CVE-2024-11394 | Low, High | ML / embeddings | transformers via sentence-transformers |
| jinja2 | PyPI | 3.1.2 | CVE-2024-22195, CVE-2024-34064 | Moderate | Templating | Jinja2 (real transitive) |
| urllib3 | PyPI | 2.0.6 | CVE-2023-45803, CVE-2024-37891 | Moderate | HTTP / TLS transport | urllib3-class TLS/HTTP stack |
| idna | PyPI | 3.6 | CVE-2024-3651 | Moderate | TLS / identity | idna |
| h11 | PyPI | 0.14.0 | CVE-2025-43859 | Critical | ASGI HTTP/1.1 parser | h11 (uvicorn) |
| anyio | PyPI | 4.0.0 | CVE-2026-63374, CVE-2026-64847 | Critical, Moderate | Async primitives | anyio |

**Expected Python CVE IDs (minimum set scanners should hit):**  
CVE-2024-24762, CVE-2024-47874, CVE-2025-54121, CVE-2024-53981, CVE-2021-41945, CVE-2024-3772, CVE-2025-71176, CVE-2024-3568, CVE-2024-11394, CVE-2024-22195, CVE-2024-34064, CVE-2023-45803, CVE-2024-37891, CVE-2024-3651, CVE-2025-43859, CVE-2026-63374, CVE-2026-64847.

OSV also attaches further IDs to some of these pins (notably `transformers==4.36.2` and `starlette==0.36.1`). Treat those as **allowed extras**, not missing plants.

`uvicorn` has no OSV hit at 0.27.x; it is present as a **range-style ASGI server** so the category exists. Detection credit for ASGI goes to `h11==0.14.0`.

## npm (pnpm lockfile) — 11 planted pins

Manifest: `sca-experiment/frontend/package.json` exact versions + `overrides` in `pnpm-workspace.yaml` (pnpm 10+ ignores `package.json#pnpm.overrides`). Lockfile: `sca-experiment/frontend/pnpm-lock.yaml`.

| Package | Ecosystem | Pinned version | Known CVE(s) | Severity | Category | Mirrors-real-category |
| --- | --- | --- | --- | --- | --- | --- |
| vite | npm | 5.2.8 | CVE-2024-45811, CVE-2024-45812, CVE-2025-30208 | Moderate | Bundler / dev server | vite |
| postcss | npm | 8.4.38 | CVE-2026-45623 | High | CSS tooling | postcss (via Vite) |
| nanoid | npm | 3.3.7 | CVE-2024-55565 | Moderate | CSS/id helper (Vite stack) | nanoid (via postcss) |
| semver | npm | 7.5.1 | CVE-2022-25883 | High | Toolchain (version parse) | semver (via Babel/Vite) |
| braces | npm | 3.0.2 | CVE-2024-4068 | High | Glob / matching | Vite/chokidar class |
| micromatch | npm | 4.0.7 | CVE-2024-4067 | Moderate | Glob / matching | Vite/chokidar class |
| cross-spawn | npm | 7.0.3 | CVE-2024-21538 | High | Process spawn (toolchain) | Vite/esbuild spawn path |
| @babel/traverse | npm | 7.23.0 | CVE-2023-45133 | Critical | Transpiler | @babel/* |
| rollup | npm | 4.17.0 | CVE-2024-47068 | High | Bundler | rollup (via Vite) |
| esbuild | npm | 0.21.5 | GHSA-67mh-4wv8-2f99 | Moderate | Bundler | esbuild (via Vite) |
| picomatch | npm | 2.3.1 | CVE-2026-33671, CVE-2026-33672 | High, Moderate | Glob / matching | picomatch (via Vite) |

**Expected npm CVE IDs (minimum set):**  
CVE-2024-45811, CVE-2024-45812, CVE-2025-30208, CVE-2026-45623, CVE-2024-55565, CVE-2022-25883, CVE-2024-4068, CVE-2024-4067, CVE-2024-21538, CVE-2023-45133, CVE-2024-47068, CVE-2026-33671, CVE-2026-33672, plus GHSA-67mh-4wv8-2f99 (esbuild; no CVE ID in OSV at check time).

Vite 5.2.8 also matches additional 2025–2026 `server.fs.deny` advisories (e.g. CVE-2025-31125, CVE-2025-32395). Count those as allowed extras on the same plant.

## Present for realism, not planted CVEs

These are required to look like Note Atlas. They are **not** in the answer key unless a scanner maps a CVE to the exact pinned version.

| Package | Ecosystem | Version | Why present |
| --- | --- | --- | --- |
| uvicorn | PyPI | `>=0.27.0,<0.28.0` | ASGI server category |
| sentence-transformers | PyPI | `>=2.2.2,<2.3.0` | ML tree (pulls torch / transformers) |
| sqlite-vec | PyPI | `>=0.1.6` | Vector/SQLite category |
| react, react-dom | npm | 18.2.0 | UI framework (no OSV hit at this version) |
| @xyflow/react | npm | 12.0.0 | Canvas / graph library (no OSV hit at this version) |
| typescript, @types/react, @types/react-dom, @vitejs/plugin-react | npm | pinned current-for-Vite-5 | toolchain |

## Scoring notes

- **True positive:** scanner reports a CVE in the “Known CVE(s)” column for that package+version.
- **Allowed extra:** another published CVE/GHSA/PYSEC on the same planted pin, or a transitive advisory not listed here.
- **False negative:** planted package+version is in the SBOM/scan target but none of its listed CVE IDs appear.
- **False positive (for this fixture):** CVE attributed to a package/version that is **not** planted and is not a documented extra on a planted pin.

`npm audit` needs a `package-lock.json`; this fixture uses **pnpm**. Use `pnpm audit` as the Node scanner (same as Phase 0).
