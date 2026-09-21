# Phase 3 — Raw consolidation of scanner findings

**Input:** `../sca-experiment/results/{pip-audit,npm-audit,trivy,grype,depcheck}.*`  
**Ground truth pairs:** [GROUND_TRUTH.md](GROUND_TRUTH.md) (32 CVE+package pairs; 31 unique IDs)  
**Dataset:** [findings.csv](findings.csv) (also copied to `../sca-experiment/results/findings.csv`)  
**Reproducible join:** [consolidate_findings.py](consolidate_findings.py)

No false-positive / false-negative scoring in this phase. `pnpm audit` is **not** one of the five CSV tool columns.

## Join rules

- One row per unique `(CVE_ID, Package)` after GHSA→CVE aliasing.
- Canonical ID prefers CVE over GHSA. Remaining GHSA-only IDs stay as GHSA (esbuild `GHSA-67mh-4wv8-2f99`).
- Alias sources: Trivy `VendorIDs`, Grype `relatedVulnerabilities`, leftover GHSA queried on OSV.
- Tool columns are Y/N for pip-audit, npm-audit, Trivy, Grype, Dependency-Check.
- `Num_tools_flagged` is the count of those five (1–5).
- `In_ground_truth?` is Y only when both the canonical ID **and** package match the Known CVE column in GROUND_TRUTH.md.
- Severity is title-cased from tools; disagreement is a range (e.g. `Medium–High`).

## Counts (134 unique pairs)

| Tool | Unique pairs | GT pairs (32) | GT unique IDs (31) |
| --- | ---: | ---: | ---: |
| pip-audit | 0 | 0 | 0 |
| npm-audit | 11 | 7 | 7 |
| Trivy | 55 | 17 | 17 |
| Grype | 134 | 24 | 24 |
| DepCheck | 12 | 8 | 8 |
| Union | 134 | 24 | 24 |

Overlap of unique pairs: exactly 1 = 68, 2 = 54, 3 = 12, 4 = 0, 5 = 0.

No row is flagged by 4 or 5 tools because pip-audit contributed zero rows (`ResolutionImpossible`). The 12 triple overlaps are npm-audit + Grype + DepCheck (Trivy did not include those npm toolchain hits under the default fs scan).

## Ground-truth pairs missed by every CSV tool (8)

| CVE_ID | Package |
| --- | --- |
| CVE-2024-24762 | fastapi |
| CVE-2024-45811 | vite |
| CVE-2024-45812 | vite |
| CVE-2025-30208 | vite |
| CVE-2024-47068 | rollup |
| CVE-2026-45623 | postcss |
| CVE-2026-33671 | picomatch |
| CVE-2026-33672 | picomatch |

CVE-2024-24762 **was** reported on `python-multipart`, so the unique CVE is in the union; the fastapi **pair** is not. Seven unique GT IDs have no row at all (all npm toolchain plants).

## Notes (not judgments)

- pip-audit 2.10.1 failed to resolve the planted `fastapi==0.109.0` / `starlette==0.36.1` set.
- Grype was run against the Syft SBOM and therefore includes Go `stdlib` / `golang.org/x/sys` matches from native binaries (esbuild). Those 68 Go rows are Grype-only.
- Trivy fs scan did not use `--include-dev-deps`; several planted npm toolchain CVEs are absent from Trivy.
- Dependency-Check unique names collapsed after GHSA→CVE aliasing (61 instances → 12 pairs in this table).
