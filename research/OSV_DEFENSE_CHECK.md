# OSV re-check (oral-defense note)

Re-queried [OSV](https://osv.dev) `POST /v1/query` on **2026-09-21** (UTC) for every true-positive row and a sample of false positives. This is a second pass after triage, not a change to `triage.csv`. All seven TP version matches held. The sampled FPs split as expected: wrong-package rows miss; unused-feature rows still hit the planted version.

Pinned versions are from `GROUND_TRUTH.md` / `package.json` / `requirements.txt`.

## True positives (all seven) — OSV HIT

| CVE / GHSA | Package | Pinned | OSV `package+version` contains this ID? | Advisory snapshot |
| --- | --- | ---: | --- | --- |
| CVE-2021-41945 | httpx | 0.19.0 | **HIT** (2 advisories on that version) | httpx `< 0.23.0` URL/`Client` validation (`GHSA-h8pj-cxx2-jfg2`) |
| CVE-2025-43859 | h11 | 0.14.0 | **HIT** | Chunked-encoding parse; OSV `versions` list includes `v0.14.0`; fixed in 0.16.0 (`GHSA-vqfr-h8mv-ghfj`) |
| CVE-2025-71176 | pytest | 8.3.4 | **HIT** | `/tmp/pytest-of-{user}` on UNIX through 9.0.2 |
| GHSA-67mh-4wv8-2f99 | esbuild | 0.21.5 | **HIT** | SEMVER introduced `0`, fixed `0.25.0` (0.21.5 is inside) |
| CVE-2026-48710 | starlette | 0.36.1 | **HIT** (14 advisories on 0.36.1) | Unvalidated `Host` used to rebuild `request.url` |
| CVE-2026-54282 | starlette | 0.36.1 | **HIT** | Same Host/URL reconstruction class |
| CVE-2026-45409 | idna | 3.6 | **HIT** (4 advisories on 3.6) | Incomplete CVE-2024-3651 fix in `idna.encode()` (`GHSA-65pc-fj4g-8rjx`) |

Defense one-liner: “Every TP is an OSV hit on the exact planted name and version; reachability is a separate, documented judgment.”

h11’s advisory also says a buggy reverse proxy is needed for *smuggling*. The TP is “vulnerable parser is on the ASGI path,” not “we demonstrated smuggling.”

## False positives sampled

| Kind | CVE | Package | Pinned | OSV | Why the FP still stands |
| --- | --- | --- | ---: | --- | --- |
| Wrong package | CVE-2024-43788 | rollup | 4.17.0 | **MISS** (2 other advisories, including the real rollup gadget CVE-2024-47068) | Webpack AutoPublicPath gadget, not rollup |
| Wrong package | CVE-2024-43788 | vite | 5.2.8 | **MISS** (15 other vite advisories) | Same Webpack CVE |
| Wrong package | CVE-2024-4067 | picomatch | 2.3.1 | **MISS** (2 other picomatch advisories: CVE-2026-33671/33672) | micromatch ReDoS |
| Unused feature | CVE-2024-11394 | transformers | 4.36.2 | **HIT** (46 advisories on that pin) | Trax deserializer; MiniLM path unused |
| Unused feature | CVE-2024-3568 | transformers | 4.36.2 | **HIT** | TF `load_repo_checkpoint`; unused |
| Unused feature | CVE-2024-56201 | jinja2 | 3.1.2 | **HIT** | Jinja sandbox; this API does not sandbox templates |
| Unused feature | CVE-2026-48817 | starlette | 0.36.1 | **HIT** | `HTTPEndpoint` getattr dispatch; FastAPI does not use that class |

## Controls (should HIT; not scored FP)

| CVE | Package | Pinned | OSV |
| --- | --- | ---: | --- |
| CVE-2024-4067 | micromatch | 4.0.7 | **HIT** (confirms the picomatch row is the mis-attribution) |
| CVE-2024-47068 | rollup | 4.17.0 | **HIT** (planted rollup CVE; no CSV tool reported it) |

## Command to repeat

```bash
# Example: one pair
curl -s https://api.osv.dev/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"package":{"name":"h11","ecosystem":"PyPI"},"version":"0.14.0"}'
```

Confirm the CVE/GHSA appears in `vulns[].id` or `vulns[].aliases`.
