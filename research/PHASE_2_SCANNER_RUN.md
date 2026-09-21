# Phase 2 — SBOM and multi-scanner run

**Target:** `sca-experiment/`  
**SBOM:** `../sca-experiment/sbom.json` (Syft CycloneDX 1.6, 198 components)  
**Raw outputs:** `../sca-experiment/results/` (not de-duplicated, not cleaned)  
**Ground truth (not scored in this phase):** [GROUND_TRUTH.md](GROUND_TRUTH.md)

No planted dependency was upgraded.

## Tool, version, command, findings

| Tool | Version | Exact command | Findings |
| --- | --- | --- | --- |
| Syft | 1.52.0 | `syft dir:sca-experiment --source-name sca-experiment --source-version 0.0.0 -o cyclonedx-json=sca-experiment/sbom.json` | 198 components (SBOM, not vulns) |
| pip-audit | 2.10.1 | `pip-audit -r sca-experiment/backend/requirements.txt --progress-spinner off --timeout 120 --format columns` | **0 vulns** — `ResolutionImpossible` (fastapi==0.109.0 vs starlette==0.36.1); raw error in `results/pip-audit.txt` |
| npm audit | 11.12.1 | `cd sca-experiment/frontend && rm -rf node_modules && npm install --ignore-scripts && npm audit --json` | **11** (2 moderate, 8 high, 1 critical) |
| pnpm audit | 12.4.2 | `cd sca-experiment/frontend && pnpm audit --json` | **33** advisories (2 low, 17 moderate, 13 high, 1 critical) |
| Trivy | 0.74.0 | `trivy fs --scanners vuln --format json --output sca-experiment/results/trivy.json sca-experiment` | **55** (3 CRITICAL, 18 HIGH, 28 MEDIUM, 6 LOW) |
| Grype | 0.119.0 | `grype sbom:sca-experiment/sbom.json -o json --file sca-experiment/results/grype.json` | **292** matches (13 Critical, 118 High, 144 Medium, 17 Low) |
| OWASP Dependency-Check | 13.0.0 | See note below | **61** vulnerability instances (51 unique names) |

### Dependency-Check command that produced JSON

NVD API with an empty key failed (`Invalid API Key, length of 0`). The report was produced with the NVD 2.0 datafeed instead:

```
dependency-check \
  --scan sca-experiment \
  --exclude "sca-experiment/results/**" \
  --exclude "sca-experiment/frontend/node_modules/**" \
  --format JSON --prettyPrint --enableExperimental \
  --project sca-experiment \
  --out sca-experiment/results \
  --nvdDatafeed "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{0}.json.gz" \
  --disableRetireJs --disableHostedSuppressions \
  --pnpm /opt/homebrew/bin/pnpm
```

Then `dependency-check-report.json` was copied to `results/depcheck.json`. Java: Homebrew OpenJDK 27 (`JAVA_HOME=/opt/homebrew/opt/openjdk`). OSS Index was disabled (token required). RetireJS was disabled after an SSL timeout on the first attempt.

## Notes

- **pip-audit** never reached CVE matching because pip could not resolve the unlocked planted `requirements.txt`. That is itself a lockfile-contrast observation.
- **pnpm audit** ran on the original pnpm tree **before** `npm install`.
- **npm install** created `frontend/package-lock.json` (needed for `npm audit`). `pnpm install` was then used to restore `node_modules`.
- Trivy logged that it suppressed some development/testing dependencies (`--include-dev-deps` was not passed).
- Counts are **as reported by each tool** (not de-duplicated across tools).
