# Stage 2 experiment — software composition analysis on a Note Atlas-shaped fixture

This section reports a controlled software-composition-analysis (SCA) experiment run on 21 September 2026. The work compared five scanners on a small FastAPI + React/Vite project whose dependencies were planted at old, published-vulnerable versions. A read-only profile of the real Note Atlas repository supplied the realism template. No planted pin was upgraded. Triage judgments are the author’s, checked against OSV on the same day and re-queried for the seven true positives plus a sample of false positives (`OSV_DEFENSE_CHECK.md`).

Supporting artifacts live under `research/` and `sca-experiment/`. The per-tool scoreboard is `results.csv`.

## Experimental design

The study had two layers. Phase 0 was a **read-only baseline** of Note Atlas: Python 3.12 FastAPI backend with an unlocked `requirements.txt` (seven direct packages, 53 resolved in the venv) and a pnpm-locked React 19 / Vite 6 frontend (eight direct packages, 139 resolved including optional native binaries). One scanner ran per ecosystem (`pip-audit` on the installed venv; `pnpm audit` on the lockfile, because `npm audit` failed with `ENOLOCK`). The application layer was effectively clean: zero advisories on declared Python packages and zero on the Node graph. The only `pip-audit` hits were two listings of one CVE in the venv’s `pip` installer, not in the app tree.

Phase 1 built a **controlled fixture** (`sca-experiment/`) that mirrored those categories rather than copying source. The backend kept an unlocked-style `requirements.txt` but pinned twelve old PyPI packages (FastAPI, Starlette, python-multipart, httpx, pydantic, pytest, transformers, jinja2, urllib3, idna, h11, anyio) to versions that OSV associated with known CVEs. Uvicorn, sentence-transformers, and sqlite-vec stayed as ranges so the ML/ASGI categories existed without being scored as ground truth. The frontend used React 18, `@xyflow/react`, and Vite 5-era toolchain pins (vite, postcss, nanoid, semver, braces, micromatch, cross-spawn, `@babel/traverse`, rollup, esbuild, picomatch) under pnpm, with a committed lockfile. That **Python-unlocked / Node-locked contrast** was an experimental variable, not an accident.

Ground truth (`GROUND_TRUTH.md`) listed 32 CVE-or-GHSA × package pairs (31 unique IDs): 18 Python pairs and 14 npm IDs including esbuild `GHSA-67mh-4wv8-2f99`. Only directly planted pins counted. Extra advisories on the same pin, and anything pulled transitively (especially through transformers), were confounders.

The unit of analysis after consolidation was a unique `(CVE_ID, Package)` row. GHSA identifiers were aliased to CVE where Trivy VendorIDs, Grype related vulnerabilities, or OSV provided a mapping. Five tools formed the comparison set: pip-audit, npm-audit, Trivy, Grype, and OWASP Dependency-Check. pnpm audit was collected as raw output but was not a column in `findings.csv`, so it does not appear in the scoreboard.

The independent variables were scanner identity, ecosystem (PyPI vs npm vs incidental Go from binaries), and lockfile style. The dependent measures were finding counts, overlap, ground-truth detection (inventory recall against the 31 planted IDs), exploitability-aware precision after triage, and unique finds (rows flagged by exactly one of the five tools).

## Tools and versions

| Tool | Version | Role |
| --- | --- | --- |
| Syft | 1.52.0 | CycloneDX 1.6 SBOM of `sca-experiment/` (198 components) |
| pip-audit | 2.10.1 | Python requirements scan |
| npm | 11.12.1 | `npm audit --json` after `npm install --ignore-scripts` |
| pnpm | 12.4.2 | `pnpm audit --json` (raw only; not in the five-tool table) |
| Trivy | 0.74.0 | Filesystem vulnerability scan |
| Grype | 0.119.0 | Scan of the Syft SBOM |
| OWASP Dependency-Check | 13.0.0 | JSON report via NVD 2.0 datafeed; RetireJS and OSS Index off |
| OSV API | 2026-09-21 | Version confirmation, leftover GHSA→CVE aliases, and a second defense pass on 7 TPs + sampled FPs |

Phase 0 used different SBOM generators (`cyclonedx-py` 7.4.0 and cdxgen 11.6.0) so the real-project SBOM is not interchangeable with the Syft fixture SBOM.

## Procedure

The real project was profiled first, without modifying application dependencies. The fixture was then created and left at the planted versions. Syft produced `sca-experiment/sbom.json`. Each scanner was run once; raw files were kept under `sca-experiment/results/`. pip-audit never reached advisory matching: pip reported `ResolutionImpossible` because `fastapi==0.109.0` and `starlette==0.36.1` do not co-install. npm audit required creating a `package-lock.json`. Trivy was run without `--include-dev-deps`. Grype was pointed at the Syft SBOM, so native binaries (esbuild) contributed Go modules.

Findings were joined into `findings.csv` (134 rows). Each row was triaged as true positive, false positive, or uncertain using OSV package+version matches and whether the vulnerable path was plausible in this FastAPI + Vite notes/LLM/canvas app. Ground-truth membership was not treated as an automatic true positive: Trax and TensorFlow checkpoint advisories on `transformers==4.36.2` were scored false positives because those loaders are unused in a MiniLM-style embedding app. After triage, all seven TPs and a sample of FPs were re-queried on OSV the same day (`OSV_DEFENSE_CHECK.md`): every TP was an OSV hit on the planted name+version; the three wrong-package FPs were OSV misses; the unused-feature FPs remained version hits.

## Variables and measures

- **Total findings.** Unique `(CVE_ID, Package)` rows a tool flagged after aliasing.
- **True positives / false positives / uncertain.** Author triage (`triage.csv`).
- **False-positive rate.** FP / (TP + FP). Uncertain rows are excluded from the denominator.
- **Ground-truth detections / detection rate.** Unique planted IDs from `GROUND_TRUTH.md` that the tool reported, divided by 31. This is inventory recall, not post-triage precision.
- **Unique finds.** Rows with `Num_tools_flagged = 1`.
- **Aggregate FPR.** Same formula on the union of 134 rows.

## Results

### Per-tool scoreboard

After GHSA→CVE aliasing there were **134 unique (CVE, package) rows** and **132 unique CVE/GHSA IDs**. Two IDs appeared on two packages: CVE-2024-4067 (micromatch and picomatch) and CVE-2024-43788 (rollup and vite).

| Tool | Total findings | TP | FP | Uncertain | FPR | GT detections | Detection rate | Unique finds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pip-audit | 0 | 0 | 0 | 0 | n/a | 0/31 | 0.0% | 0 |
| npm-audit | 11 | 1 | 3 | 7 | 3/4 = 75.0% | 7/31 | 22.6% | 0 |
| Trivy | 55 | 6 | 13 | 36 | 13/19 = 68.4% | 17/31 | 54.8% | 0 |
| Grype | 134 | 7 | 84 | 43 | 84/91 = 92.3% | 24/31 | 77.4% | 68 |
| DepCheck | 12 | 1 | 3 | 8 | 3/4 = 75.0% | 8/31 | 25.8% | 0 |
| Union | 134 | 7 | 84 | 43 | 84/91 = 92.3% | 24/31 | 77.4% | 68 |

pip-audit contributed nothing because resolution failed on the unlocked planted set. Grype’s row equals the union: every consolidated finding appeared in Grype. The 68 unique finds were all Grype-only Go `stdlib` / `golang.org/x/sys` matches from the esbuild binary in the Syft SBOM; all 68 were triaged as false positives (wrong ecosystem for this application). No other tool had a singleton.

Overlap of the 134 rows: 68 flagged by exactly one tool, 54 by two (almost all Trivy+Grype on PyPI), 12 by three (npm-audit + Grype + DepCheck on the npm toolchain). None were flagged by four or five tools, because pip-audit was empty and Trivy skipped several npm dev-toolchain hits.

The seven true positives were httpx CVE-2021-41945, h11 CVE-2025-43859, pytest CVE-2025-71176, esbuild GHSA-67mh-4wv8-2f99, Starlette Host-header CVE-2026-48710 and CVE-2026-54282, and an extra on the planted idna pin (CVE-2026-45409) that ground truth had not listed. npm-audit and Dependency-Check’s only true positive was esbuild; Trivy missed that hit.

### Overall

| Quantity | Value |
| --- | --- |
| Unique (CVE, package) rows | 134 |
| Unique CVE/GHSA IDs | 132 |
| True positives | 7 |
| False positives | 84 |
| Uncertain | 43 |
| Aggregate FPR | 84 / (7 + 84) = **92.3%** |
| FP share of all rows | 84 / 134 = 62.7% |
| Confirmed-TP share of all rows | 7 / 134 = 5.2% |
| Ground-truth union | 24 / 31 planted IDs (77.4%) |
| Planted IDs missed by every CSV tool | 7 (three vite, rollup, postcss, two picomatch) |

If the 68 Go rows are set aside, 66 application-ecosystem rows remain: 7 TP, 16 FP, 43 Uncertain, FPR 16/23 = **69.6%**. False positives are still the majority of *decided* rows. The Go slice is scanner artifact, not application risk, but it is what a Grype-on-Syft-SBOM user would have seen.

Clear misattributions included Webpack CVE-2024-43788 reported on vite and rollup (OSV does not affect those pins) and micromatch CVE-2024-4067 reported on picomatch.

### Comparison with the Phase 0 real project

The controlled fixture **looked like** Note Atlas (same ecosystems and categories, same lockfile contrast, same Vite native-binary fan-out) and **did not scan like** Note Atlas.

On the real repo, a one-scanner-per-ecosystem check found essentially nothing in the application graphs: `pnpm audit` reported zero vulnerabilities; `pip-audit` reported one CVE in `pip` itself. `npm audit` could not run (`ENOLOCK`). There was no five-tool disagreement to measure, and no exploitability triage, because there was almost nothing to triage.

On the fixture, counts ran from 0 (pip-audit) to 134 unique rows (Grype), with raw Grype matches at 292 before de-duplication. That spread is an artifact of planted old pins plus Grype’s Go inventory. It is not evidence that Note Atlas in production currently carries 134 vulnerabilities.

Two structural similarities still matter. First, **unlocked Python** caused scanner failure in the fixture (`ResolutionImpossible`) and would have been invisible in Phase 0 only because the real venv was already installed and scanned via `--path`. The contrast the design set out to study showed up as “tool cannot even resolve the manifest.” Second, Phase 0 already warned that a large share of Node “resolved” count is optional native binaries. Running Grype on a Syft SBOM of the *real* frontend would likely produce the same class of Go stdlib noise; the fixture demonstrated that noise instead of the real repo, because Phase 0 never ran Grype.

So the controlled project behaved like the real one as a **dependency-shape replica**, and unlike it as a **vulnerability-volume replica**. Using the fixture’s false-positive rate as an estimate of Note Atlas’s production-scan quality would be wrong. Using it as evidence that these scanners disagree, miss planted toolchain CVEs, and over-report binary-embedded runtimes is the valid inference.

### Claim versus evidence

| Published-style claim | Evidence from this run | Verdict |
| --- | --- | --- |
| SCA tools report widely different counts [1] | After the same aliasing pass, unique-pair counts were 0, 11, 55, 134, and 12. Raw Grype listed 292 matches; pip-audit listed 0. pnpm audit (not in the table) listed 33 Node advisories versus npm audit’s 11. Overlap never reached 4/5 tools. | **Supported** |
| False positives are a large share of findings [2] | 84 of 134 rows were FP (62.7%). Among decided rows, aggregate FPR was 92.3%, or 69.6% with Go removed. Confirmed TPs were 7 (5.2% of rows). Forty-three further rows stayed Uncertain rather than being scored TP. | **Supported** |
| No single tool catches everything [3] | The best inventory recall was Grype at 24/31 planted IDs (77.4%). The union was the same 24/31: Grype’s extra coverage was Go FPs, not extra ground-truth IDs beyond that 24. Seven planted IDs (vite ×3, rollup, postcss, picomatch ×2) were missed by every CSV tool. Trivy found six of seven TPs but missed esbuild; npm-audit and DepCheck found esbuild but almost none of the Python TPs. pip-audit found nothing. | **Supported** |

The third claim is supported as “no tool had complete planted-CVE recall,” not as “the union beat Grype on ground truth.” On this fixture Grype *was* the union for inventory. Completeness still failed: 7 of 31 planted IDs, including the three vite plants, never appeared.

**[1]** Imtiaz, N., Thorn, S., and Williams, L. (2021). A comparative study of vulnerability reporting by software composition analysis tools. In *ESEM ’21*. They reported vulnerable-dependency counts from 17 to 332 (Maven) and 32 to 239 (npm) across nine tools. DOI [10.1145/3475716.3475769](https://doi.org/10.1145/3475716.3475769).

**[2]** Pashchenko, I., Plate, H., Ponta, S. E., Sabetta, A., and Massacci, F. (2022). Vuln4Real: A methodology for counting actually vulnerable dependencies. *IEEE Transactions on Software Engineering*, 48(5). They treated non-deployed / non-exploitable dependency alerts as false alerts and removed 27% of vulnerable-direct and 21% of vulnerable-transitive alerts in their SAP Java sample. DOI [10.1109/TSE.2020.3025443](https://doi.org/10.1109/TSE.2020.3025443). (The 2018 precursor found about 20% of vulnerable dependencies were not deployed: DOI [10.1145/3239235.3268920](https://doi.org/10.1145/3239235.3268920).)

**[3]** Same study as [1]: Imtiaz et al. conclude that “practitioners should not rely on any single tool at the present, as that can result in missing known vulnerabilities.” DOI [10.1145/3475716.3475769](https://doi.org/10.1145/3475716.3475769).

## Limitations

The fixture is small: a handful of FastAPI routes and a canvas page, not a full Note Atlas clone. Reachability therefore mixed “this stub imports it” with “a project of this category would.” Another analyst could move some Uncertain multipart or tokenizer rows into TP or FP.

Triage is the author’s. OSV package+version queries constrained the obvious misattributions, but unused-feature calls (Trax, Jinja sandbox, HTTPEndpoint) are judgment. Matching was metadata-based (manifest version vs advisory range), not a proof that a payload executes. The second OSV pass confirmed version matches for all seven TPs; it did not re-score reachability. h11’s advisory also requires a buggy reverse proxy for request smuggling — the TP is “the affected parser is on the ASGI path,” not a demonstrated smuggling exploit.

Phase 0 ran one scanner per ecosystem on current pins. It cannot support a numeric FPR comparison with the five-tool fixture. Native-binary Go inflation was hypothesized from the real lockfile and observed only on the fixture.

pip-audit’s zero is a resolution failure, not a claim that Python was clean. Trivy was run without `--include-dev-deps`. Dependency-Check used a public NVD feed without OSS Index or RetireJS. Results are for these versions on one day (21 September 2026).

Ground truth listed expected CVEs for detection, not an exploit lab. Several “known CVE” plants (Trax, TF checkpoint, form parsers with no form routes) failed the exploitability bar. Inventory recall and precision after triage answer different questions; both are reported.

---

## Appendix — AI use

All experiment phases in this repository were executed in **Cursor** using the **Cursor Grok 4.6** agent (the in-IDE coding assistant). No other generative model was used to plant versions, run scanners, join CSVs, or write triage. Scanner CLIs, Syft, OSV’s HTTP API, and Homebrew packages are not AI tools.

Cursor **Canvases** were used only to display consolidated tables beside the chat; they did not choose verdicts.

System “briefly inform the user” notifications after background installs are omitted; they were not experiment prompts.

### Prompts (verbatim user queries)

**Phase 0 — real-project profile**

> I'm starting a controlled software-supply-chain-security experiment for a graduate course. Before building the controlled test project, analyze one of my REAL projects to understand its actual dependency profile — this is the real-world baseline I'll compare the controlled experiment against.
>
> The project is at: \<PATH TO YOUR PROJECT, e.g. ~/projects/kemiko\>
>
> Do the following, read-only — do NOT modify, update, or fix anything:
> 1. Detect the stack and dependency manifests present (e.g. requirements.txt / pyproject.toml, package.json, lockfiles).
> 2. Count: total direct dependencies vs. total resolved (including transitive) for each ecosystem.
> 3. Generate a CycloneDX SBOM of the project → save as `baseline/sbom-real.json`.
> 4. Run ONE scanner per ecosystem as a quick reality check (pip-audit for Python, npm audit for Node) and save raw output to `baseline/`. Report how many vulnerabilities each found.
> 5. Write `baseline/REAL_PROJECT_PROFILE.md` summarizing: stack, dependency counts (direct vs transitive), ecosystems in use, the specific package categories present (web framework, HTTP client, parsing, image handling, auth, etc.), and the headline vulnerability counts.
>
> Purpose: I'll use this profile to make my controlled test project realistic — mirroring the same ecosystems and package categories my real work actually depends on. Do not include any proprietary code contents in the summary; just the dependency/technical profile.
>
> Show me REAL_PROJECT_PROFILE.md when done.

**Phase 1 — controlled fixture**

> make all documents for phased prompts is to be declared in research/
>
> Continuing the experiment. Now create the CONTROLLED test project — the main experiment, where I deliberately plant known-vulnerable dependencies so I have ground truth.
>
> Use `baseline/REAL_PROJECT_PROFILE.md` from Phase 0 as the realism template. Mirror Note Atlas's actual stack and category mix, but pin dependencies to OLD, known-vulnerable versions.
>
> Create `sca-experiment/` with:
> 1. Backend: FastAPI (NOT Django), Python, with an UNPINNED-style requirements.txt BUT pin 8–12 packages to OLD versions carrying well-documented CVEs, matching the Phase 0 categories: web framework (fastapi/starlette), ASGI (uvicorn), HTTP client (httpx or requests), validation (pydantic), testing (pytest), plus at least one ML/embeddings-class package to reproduce a large transitive tree. Use versions whose CVEs are real and published.
> 2. Frontend: React + Vite + TypeScript via PNPM (generate a pnpm-lock.yaml), mirroring Note Atlas: React, a canvas/graph library (@xyflow/react-class), Vite toolchain. Pin 8–12 npm packages to OLD versions with known CVEs. Keep the lockfile (this mirrors the real project's locked frontend).
> 3. Preserve the real project's LOCKFILE CONTRAST: Python range-pinned/unlocked, Node locked. This contrast is itself a variable I want to study.
> 4. Minimal FastAPI app + minimal React canvas component so it's plausible; dependencies are the point.
> 5. GROUND_TRUTH.md: table [Package | Ecosystem | Pinned version | Known CVE(s) | Severity | Category | Mirrors-real-category]. List the specific CVE IDs I expect scanners to find.
>
> Do not fix or update any vulnerable dependency. Show me GROUND_TRUTH.md and the structure.

**Phase 2 — SBOM and scanners**

> Continuing the sca-experiment (the controlled project in sca-experiment/). Generate an SBOM and run multiple SCA scanners against it, capturing each tool's raw output. Install any missing tool.
>
> 1. SBOM: use Syft to generate a CycloneDX SBOM → save as `sca-experiment/sbom.json`.
> 2. Run these scanners; save each one's raw output verbatim into `sca-experiment/results/`:
>    - pip-audit on requirements.txt → results/pip-audit.txt
>    - npm audit (after npm install) → results/npm-audit.json (--json)
>    - pnpm audit (frontend, after pnpm install) → results/pnpm-audit.json (--json)
>    - Trivy filesystem scan → results/trivy.json (-f json)
>    - Grype scan of the folder or sbom.json → results/grype.json
>    - OWASP Dependency-Check → results/depcheck.json (JSON report)
> 3. For each tool print: tool name, version, exact command run, and a one-line count of vulnerabilities reported.
>
> Keep every raw output file — these are experiment appendices. Do not de-duplicate or clean anything. End with a summary: tool, version, command, total findings.

**Phase 3 — consolidation**

> Continuing the sca-experiment. Consolidate every scanner's findings from sca-experiment/results/ into one comparison dataset. Produce `findings.csv` (and show it) with:
>
> [CVE_ID | Package | Ecosystem | Severity | pip-audit? | npm-audit? | Trivy? | Grype? | DepCheck? | Num_tools_flagged | In_ground_truth?]
>
> Rules:
> - One row per unique (CVE_ID, Package) pair across ALL tools.
> - Y/N in each tool column for whether that tool reported it.
> - Num_tools_flagged = how many of the 5 tools flagged it (1–5).
> - In_ground_truth? = Y if the CVE+package is in GROUND_TRUTH.md, else N.
> - Severity from the tools; if they disagree, note the range.
>
> Then give me three summary tables:
>   A. Per-tool totals.
>   B. Overlap: how many CVEs found by exactly 1, 2, 3, 4, or all 5 tools.
>   C. Ground-truth coverage: of the CVEs in GROUND_TRUTH.md, how many each tool caught.
>
> No false-positive judgments yet — raw consolidation only. Save findings.csv.

**Phase 4 — triage**

> Continuing the sca-experiment. Triage each finding in findings.csv as TRUE POSITIVE, FALSE POSITIVE, or UNCERTAIN, with reasoning. This is the core evidence of the experiment.
>
> For EACH row, add and fill: [Verdict (TP/FP/Uncertain) | Reachable? | Reasoning]
>
> Verdict rules:
> - TRUE POSITIVE: the package+version genuinely carries that CVE AND the vulnerable code path could plausibly be reached in a project like this.
> - FALSE POSITIVE: the CVE doesn't actually apply — wrong version match, withdrawn/disputed CVE, unused affected feature, dev-only dependency flagged as production, or duplicate/misattributed.
> - UNCERTAIN: can't tell without deeper analysis — say why.
> "Reachable?" = Y/N/Unknown on whether the vulnerable function is actually invoked here.
> "Reasoning" = one or two sentences.
>
> Be strict and honest — do not label something TP just because a tool flagged it. Where a tool flagged a CVE NOT in GROUND_TRUTH.md, scrutinise it hard: it may be a real find the ground truth missed, or a false positive.
>
> Save the enriched table as `triage.csv` and show it. Then compute per tool:
>   - False-positive rate = FP / (TP + FP)
>   - Detection rate vs. ground truth = ground-truth CVEs caught / total ground-truth CVEs

**Phase 5 — results and write-up**

> Continuing the sca-experiment. Using triage.csv and the summary tables, produce the final results and a draft write-up.
>
> 1. RESULTS table, per tool: total findings, true positives, false positives, false-positive rate, ground-truth detections, detection rate, and unique finds.
> 2. Overall: total unique CVEs, TP vs FP counts, aggregate false-positive rate.
> 3. Also compare against the Phase 0 real project: note how the controlled results (false-positive rate, tool disagreement) compare to the quick scan of my real project — does the controlled project behave like the real one?
> 4. "Claim vs. evidence" table testing published claims against MY data:
>    - "SCA tools report widely different counts" → my evidence → supported/partial/unsupported
>    - "False positives are a large share of findings" → my evidence → …
>    - "No single tool catches everything" → my evidence → …
> 5. Draft the Stage 2 Experiment section (for a 6–10 page report), subsections: Experimental design · Tools & versions · Procedure · Variables/measures · Results. Plain prose, past tense. Note limitations honestly (small project, my own triage judgment, metadata-based matching, single real-project baseline).
> 6. List every AI tool used across all phases, with the prompts, for the AI-use appendix.
>
> Save the write-up as `EXPERIMENT_writeup.md` and the results table as `results.csv`.

**Defense check — OSV re-query and citations**

> Verify the 7 TPs + a few FPs against OSV yourself (30 min, protects you at defense).
> Add the three inline citations to the claim-vs-evidence table.
