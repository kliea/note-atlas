# Phase 4 — Exploitability-aware triage

**Input:** [findings.csv](findings.csv) (134 unique CVE+package rows)  
**Output:** [triage.csv](triage.csv) (copy at `../sca-experiment/results/triage.csv`)  
**Join script:** [triage_findings.py](triage_findings.py)

Pins were not upgraded. Verdicts are **not** “the scanner printed a CVE”. They ask whether the planted/resolved version actually carries the advisory **and** whether the vulnerable path is plausible in a FastAPI + Vite notes/LLM/canvas app like this fixture.

## Rules used

| Verdict | Meaning |
| --- | --- |
| TP | OSV (2026-09-21) matches package+version, and the affected subsystem is on a hot path (ASGI HTTP parse, httpx client, pytest, Vite/esbuild `dev`, Host-header `request.url`). |
| FP | Wrong package/version (OSV miss), misattributed Go stdlib from the esbuild binary, or an unused specialized feature (Trax/MobileViT/MaskFormer/TF/LightGlue loaders, Jinja sandbox, Starlette `HTTPEndpoint`/`StaticFiles`, python-multipart non-default write). |
| Uncertain | Version match is real, but exploitability needs a feature this stub does not exercise (multipart forms, Jinja `xmlattr`, IDN, urllib3 proxies, tokenizer ReDoS, untrusted globs). |

`Reachable?` is Y/N/Unknown for **this** tree (and the Note Atlas-shaped category it stands in for), not “could some other product hit it”.

Ground-truth membership is **not** an automatic TP. Two GT transformers advisories (Trax, TF checkpoint) were scored FP as unused loaders.

## Headline counts (134 rows)

| Verdict | Rows |
| --- | ---: |
| TP | 7 |
| FP | 84 |
| Uncertain | 43 |

68 of the 84 FPs are Grype-only Go `stdlib` / `golang.org/x/sys` rows from the Syft SBOM of native binaries.

## Per-tool rates

False-positive rate = FP / (TP + FP). Uncertain is excluded from that denominator.  
Detection rate = unique GROUND_TRUTH.md CVE/GHSA IDs flagged / 31 (inventory catch, independent of triage verdict).

| Tool | Flagged | TP | FP | Uncertain | FPR | GT detection |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| pip-audit | 0 | 0 | 0 | 0 | n/a | 0/31 (0.0%) |
| npm-audit | 11 | 1 | 3 | 7 | 3/4 = 75.0% | 7/31 (22.6%) |
| Trivy | 55 | 6 | 13 | 36 | 13/19 = 68.4% | 17/31 (54.8%) |
| Grype | 134 | 7 | 84 | 43 | 84/91 = 92.3% | 24/31 (77.4%) |
| DepCheck | 12 | 1 | 3 | 8 | 3/4 = 75.0% | 8/31 (25.8%) |

pip-audit still has no rows (`ResolutionImpossible`). npm-audit/DepCheck’s single TP is esbuild `GHSA-67mh-4wv8-2f99`. Trivy missed that npm toolchain hit (no `--include-dev-deps`). Grype’s high FPR is dominated by Go binary inventory.

## Clear misattributions (FP, not in GT)

| CVE | Package as reported | Actual |
| --- | --- | --- |
| CVE-2024-4067 | picomatch | micromatch ReDoS; picomatch 2.3.1 not affected |
| CVE-2024-43788 | rollup, vite | Webpack DOM-clobbering gadget; OSV does not match these pins |

## GT extras the table missed that triage still treated as real

`CVE-2026-45409` on `idna==3.6` (incomplete CVE-2024-3651 fix) is a genuine extra on a planted pin, scored TP with Reachable=Unknown.
