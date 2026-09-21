# SCA experiment — phased documents

All **phase prompts, ground truth, and methodology notes** for the software-supply-chain-security experiment live here. Application code for the controlled fixture is in `sca-experiment/`. The real-project baseline (Phase 0 artifacts) is in `baseline/`.

| Phase | Document | Role |
| --- | --- | --- |
| 0 | [../baseline/REAL_PROJECT_PROFILE.md](../baseline/REAL_PROJECT_PROFILE.md) | Realism template from Note Atlas (do not treat as ground truth) |
| 1 | [PHASE_1_CONTROLLED_PROJECT.md](PHASE_1_CONTROLLED_PROJECT.md) | Controlled fixture design and lockfile contrast |
| 1 | [GROUND_TRUTH.md](GROUND_TRUTH.md) | Planted packages, pinned versions, expected CVE IDs |
| 2 | [PHASE_2_SCANNER_RUN.md](PHASE_2_SCANNER_RUN.md) | Syft SBOM + multi-scanner raw outputs and counts |
| 3 | [PHASE_3_CONSOLIDATION.md](PHASE_3_CONSOLIDATION.md) | Raw join of five scanners into [findings.csv](findings.csv) |
| 4 | [PHASE_4_TRIAGE.md](PHASE_4_TRIAGE.md) | TP/FP/Uncertain triage in [triage.csv](triage.csv) |
| 5 | [EXPERIMENT_writeup.md](EXPERIMENT_writeup.md) | Stage 2 results draft and AI-use appendix; scoreboard [results.csv](results.csv) |
| 5 | [OSV_DEFENSE_CHECK.md](OSV_DEFENSE_CHECK.md) | Second OSV pass on the 7 TPs and sampled FPs |

Do not upgrade or patch planted versions. Findings that are **not** listed in `GROUND_TRUTH.md` are confounders (transitive extras, advisory aliases, scanner disagreement) until Phase 4 triage.
