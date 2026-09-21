#!/usr/bin/env python3
"""Phase 4 — exploitability-aware triage of findings.csv. Pins are not changed."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/klinthjeraldmatugas/Documents/DEV/ATLAS")
SRC = ROOT / "research/findings.csv"
OUT_RESEARCH = ROOT / "research/triage.csv"
OUT_RESULTS = ROOT / "sca-experiment/results/triage.csv"

# Verdict, Reachable, Reasoning — keyed by (CVE_ID, Package).
# Reachable is for THIS fixture / a Note Atlas-like FastAPI+Vite app.
# OSV 2026-09-21 used to confirm package+version matches.
TRIAGE: dict[tuple[str, str], tuple[str, str, str]] = {
    # --- planted GT, version-confirmed ---
    ("CVE-2021-41945", "httpx"): (
        "TP",
        "Y",
        "OSV confirms httpx 0.19.0 is affected (URL/Client input validation). The fixture and a Note Atlas-like app call httpx.get, so that code path is on the HTTP-client hot path.",
    ),
    ("CVE-2025-43859", "h11"): (
        "TP",
        "Y",
        "h11 0.14.0 accepts malformed Chunked-Encoding bodies. uvicorn/Starlette parse HTTP/1.1 through h11 on every request, so the parser is reached.",
    ),
    ("CVE-2025-71176", "pytest"): (
        "TP",
        "Y",
        "pytest through 9.x uses /tmp/pytest-of-{user} on UNIX. This backend has pytest tests, so the directory pattern is used when tests run (test-time, not production request path).",
    ),
    ("GHSA-67mh-4wv8-2f99", "esbuild"): (
        "TP",
        "Y",
        "esbuild < 0.25.0 sets CORS * on the dev server, including SSE. `vite`/`esbuild` serve is how this frontend is developed, so a website can hit the local dev server.",
    ),
    ("CVE-2026-48710", "starlette"): (
        "TP",
        "Y",
        "OSV confirms starlette 0.36.1 rebuilds request.url from an unvalidated Host header. Every FastAPI request constructs request.url, so the poisoned-path code runs even if this app does not use path-based auth.",
    ),
    ("CVE-2026-54282", "starlette"): (
        "TP",
        "Y",
        "Same Host-header reconstruction class as CVE-2026-48710: request.url.hostname is built on the ASGI request path that FastAPI always takes.",
    ),
    ("CVE-2026-45409", "idna"): (
        "TP",
        "Unknown",
        "OSV matches idna 3.6: incomplete CVE-2024-3651 fix in idna.encode(). Ground truth missed this extra. encode() is only hit for internationalized hostnames, which this fixture does not use.",
    ),
    # GT but unused specialized feature
    ("CVE-2024-11394", "transformers"): (
        "FP",
        "N",
        "Version is affected, but the advisory is Trax-model pickle deserialization. A MiniLM embedding app does not load Trax models, so the vulnerable loader is unused.",
    ),
    ("CVE-2024-3568", "transformers"): (
        "FP",
        "N",
        "Advisory is TFPreTrainedModel.load_repo_checkpoint() (TensorFlow pickle). This stack uses PyTorch sentence-transformers/MiniLM, not the TF checkpoint path.",
    ),
    # GT version-true, reachability not shown
    ("CVE-2022-25883", "semver"): (
        "Uncertain",
        "Unknown",
        "semver 7.5.1 has Range ReDoS, and Vite/npm call semver, but exploitation needs an attacker-controlled range string rather than the trusted package.json pins.",
    ),
    ("CVE-2023-45133", "@babel/traverse"): (
        "Uncertain",
        "Unknown",
        "@babel/traverse 7.23.0 RCE requires compiling attacker-crafted JS. Vite's React plugin does compile this app, but the source is first-party, not untrusted plugins.",
    ),
    ("CVE-2023-45803", "urllib3"): (
        "Uncertain",
        "Unknown",
        "urllib3 2.0.6 is affected (body not stripped on 301/302/303). httpx 0.19 uses httpcore; whether transformers/huggingface_hub actually issues a converting redirect is not shown.",
    ),
    ("CVE-2024-21538", "cross-spawn"): (
        "Uncertain",
        "Unknown",
        "cross-spawn 7.0.3 ReDoS is real, and Vite/npm spawn processes, but the bug needs a huge crafted argument, not the short commands this toolchain issues.",
    ),
    ("CVE-2024-22195", "jinja2"): (
        "Uncertain",
        "N",
        "xmlattr XSS is real on jinja2 3.1.2, but this FastAPI fixture (and typical JSON notes API) does not render Jinja templates or use xmlattr.",
    ),
    ("CVE-2024-24762", "python-multipart"): (
        "Uncertain",
        "N",
        "Content-Type ReDoS is real on 0.0.6, but it fires while parsing multipart/form-data. Endpoints here are JSON; no Form/File routes exist.",
    ),
    ("CVE-2024-34064", "jinja2"): (
        "Uncertain",
        "N",
        "xmlattr key injection is real on 3.1.2. Same as CVE-2024-22195: no template rendering in this API.",
    ),
    ("CVE-2024-3651", "idna"): (
        "Uncertain",
        "Unknown",
        "idna.encode() quadratic DoS is real on 3.6, but encode() is only used for IDN hosts; this app talks to 127.0.0.1 / ordinary ASCII names.",
    ),
    ("CVE-2024-3772", "pydantic"): (
        "Uncertain",
        "N",
        "ReDoS is in Pydantic constrained/email-like validators before 2.4. Health/NoteIn use plain str fields, so that regex is not invoked.",
    ),
    ("CVE-2024-37891", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Proxy-Authorization leak on cross-origin redirects is real on 2.0.6, but it needs urllib3 requests without ProxyManager; this fixture never configures an HTTP proxy.",
    ),
    ("CVE-2024-4067", "micromatch"): (
        "Uncertain",
        "Unknown",
        "micromatch 4.0.7 ReDoS is real and Vite uses micromatch for globs, but the trigger is an attacker-controlled glob, not first-party source paths.",
    ),
    ("CVE-2024-4068", "braces"): (
        "Uncertain",
        "Unknown",
        "braces < 3.0.3 can memory-exhaust on imbalanced-brace input. Vite/chokidar may call braces, but only on this repo's own glob patterns.",
    ),
    ("CVE-2024-47874", "starlette"): (
        "Uncertain",
        "N",
        "Unbounded buffering of filename-less multipart parts is real on 0.36.1. FastAPI only parses multipart when Form/File is declared; this app has neither.",
    ),
    ("CVE-2024-53981", "python-multipart"): (
        "Uncertain",
        "N",
        "Deformed multipart-boundary DoS is real on 0.0.6. No multipart endpoints, so the parser is not on the request path.",
    ),
    ("CVE-2024-55565", "nanoid"): (
        "Uncertain",
        "Unknown",
        "nanoid 3.3.7 mishandles non-integer sizes. Vite uses nanoid internally, but typically with integer lengths; this is not used as a security token here.",
    ),
    ("CVE-2025-54121", "starlette"): (
        "Uncertain",
        "N",
        "Large multipart spool DoS is real on 0.36.1. Same as other form bugs: this API does not accept multipart bodies.",
    ),
    ("CVE-2026-63374", "anyio"): (
        "Uncertain",
        "N",
        "TLSStream IDNA-2003 cert spoofing is real on anyio 4.0.0, but it needs connect_tcp/TLSStream to an internationalized hostname. This app uses httpx to 127.0.0.1.",
    ),
    ("CVE-2026-64847", "anyio"): (
        "Uncertain",
        "N",
        "Process-pool workers can block on undrained stderr. FastAPI/Starlette use anyio for async I/O, not AnyIO process pools.",
    ),
    # --- extras: misattribution ---
    ("CVE-2024-4067", "picomatch"): (
        "FP",
        "N",
        "CVE-2024-4067 is micromatch ReDoS. OSV does not list picomatch 2.3.1 as affected; this is a wrong-package alias.",
    ),
    ("CVE-2024-43788", "rollup"): (
        "FP",
        "N",
        "Advisory is a Webpack AutoPublicPathRuntimeModule DOM-clobbering gadget. OSV does not affect rollup 4.17.0 (rollup's own gadget is CVE-2024-47068, which no tool reported).",
    ),
    ("CVE-2024-43788", "vite"): (
        "FP",
        "N",
        "Same Webpack CVE misattributed to vite 5.2.8. OSV does not match; Vite's planted fs.deny CVEs were not reported.",
    ),
    # --- extras: unused specialized features ---
    ("CVE-2024-11392", "transformers"): (
        "FP",
        "N",
        "MobileViTV2 untrusted-data RCE. This app class loads MiniLM embeddings, not MobileViT, so the vulnerable deserializer is unused.",
    ),
    ("CVE-2024-11393", "transformers"): (
        "FP",
        "N",
        "MaskFormer untrusted-data RCE. MaskFormer is not on the MiniLM/sentence-transformers path.",
    ),
    ("CVE-2026-1839", "transformers"): (
        "FP",
        "N",
        "Trainer checkpoint torch.load() RCE. The fixture never trains or loads Trainer checkpoints; it only names an embed model string.",
    ),
    ("CVE-2026-4372", "transformers"): (
        "FP",
        "N",
        "_attn_implementation_internal config injection requires loading a malicious model config. This app does not load user-supplied transformers configs.",
    ),
    ("CVE-2026-5241", "transformers"): (
        "FP",
        "N",
        "LightGlue nested-config policy bypass. LightGlue is unused in a MiniLM notes/embedding app.",
    ),
    ("CVE-2024-56201", "jinja2"): (
        "FP",
        "N",
        "Sandbox breakout via malicious filenames. FastAPI JSON APIs do not enable Jinja's sandbox or render untrusted templates.",
    ),
    ("CVE-2024-56326", "jinja2"): (
        "FP",
        "N",
        "Sandbox breakout via format method. Unused: no Jinja sandbox in this stack.",
    ),
    ("CVE-2025-27516", "jinja2"): (
        "FP",
        "N",
        "Sandbox breakout via attr filter selecting format. Unused: no Jinja sandbox.",
    ),
    ("CVE-2026-24486", "python-multipart"): (
        "FP",
        "N",
        "Arbitrary file write only via a non-default configuration. Default FastAPI form parsing does not enable that mode, and this app has no forms.",
    ),
    ("CVE-2026-48817", "starlette"): (
        "FP",
        "N",
        "getattr-based HTTP method dispatch on HTTPEndpoint. FastAPI uses its own routing, not Starlette HTTPEndpoint, so the gadget is unused.",
    ),
    ("CVE-2026-48818", "starlette"): (
        "FP",
        "N",
        "StaticFiles UNC/SSRF on Windows. This app does not mount StaticFiles and is not a Windows-targeted service.",
    ),
    # --- extras: version-true, need more analysis ---
    ("CVE-2024-12720", "transformers"): (
        "Uncertain",
        "Unknown",
        "ReDoS in transformers 4.36.2 is version-true. Whether the regex sits on MiniLM tokenization of note text needs a file-level trace.",
    ),
    ("CVE-2025-1194", "transformers"): (
        "Uncertain",
        "Unknown",
        "Another transformers ReDoS extra on 4.36.2. Cannot tell without mapping the regex to the embedding tokenizer this app would call.",
    ),
    ("CVE-2025-2099", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-3263", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-3264", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-3777", "transformers"): (
        "Uncertain",
        "Unknown",
        "Improper input validation extra on transformers 4.36.2. Need the exact function to know if embedding inference hits it.",
    ),
    ("CVE-2025-3933", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-5197", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-6051", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-6638", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2025-6921", "transformers"): (
        "Uncertain",
        "Unknown",
        "transformers ReDoS extra on 4.36.2; component vs MiniLM path not verified.",
    ),
    ("CVE-2026-9856", "transformers"): (
        "Uncertain",
        "Unknown",
        "Path traversal extra on transformers 4.36.2. Depends on whether local/user-controlled file paths are passed into the library; this fixture does not load models at all.",
    ),
    ("CVE-2025-50181", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Redirects still followed when retries are disabled on PoolManager. Requires that specific constructor pattern, which this code does not use directly.",
    ),
    ("CVE-2025-66418", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Unbounded decompression-chain extra on 2.0.6. Real if something fetches attacker HTTP with urllib3; httpx 0.19 does not use urllib3.",
    ),
    ("CVE-2025-66471", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Streaming API decompression-bomb extra on 2.0.6. Same urllib3-vs-httpx uncertainty as other extras.",
    ),
    ("CVE-2026-21441", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Redirect decompression-bomb bypass extra on 2.0.6. Needs urllib3 streaming + redirects; not shown here.",
    ),
    ("CVE-2026-44431", "urllib3"): (
        "Uncertain",
        "Unknown",
        "Sensitive headers forwarded on proxied low-level redirects. Needs a proxy/redirect setup this fixture does not have.",
    ),
    ("CVE-2026-40347", "python-multipart"): (
        "Uncertain",
        "N",
        "DoS via large multipart preamble is real on 0.0.6, but there are no multipart endpoints to parse that body.",
    ),
    ("CVE-2026-42561", "python-multipart"): (
        "Uncertain",
        "N",
        "Unbounded multipart part-header DoS is real on 0.0.6; parser not on this API's request path.",
    ),
    ("CVE-2026-53537", "python-multipart"): (
        "Uncertain",
        "N",
        "Content-Disposition parameter smuggling is real on 0.0.6; no form parsing here.",
    ),
    ("CVE-2026-53538", "python-multipart"): (
        "Uncertain",
        "N",
        "Semicolon querystring smuggling is real on 0.0.6; no form/querystring parser use shown.",
    ),
    ("CVE-2026-53539", "python-multipart"): (
        "Uncertain",
        "N",
        "Quadratic querystring parsing DoS is real on 0.0.6; not on the JSON request path.",
    ),
    ("CVE-2026-53540", "python-multipart"): (
        "Uncertain",
        "N",
        "Negative Content-Length buffering is real on 0.0.6; parse_form is not called.",
    ),
    ("CVE-2026-54283", "starlette"): (
        "Uncertain",
        "N",
        "request.form() size limits ignored for urlencoded bodies. This app never calls request.form().",
    ),
    ("CVE-2026-41305", "postcss"): (
        "Uncertain",
        "Unknown",
        "PostCSS 8.4.38 XSS via unescaped </style> in stringify is version-true (GT listed a different postcss CVE). Needs untrusted CSS flowing through stringify during Vite build.",
    ),
}

GO_REASON = (
    "FP",
    "N",
    "Misattributed inventory: this project has no Go modules. Grype reported Go stdlib/x/sys CVEs from the esbuild native binary inside the Syft SBOM, which is not the application attack surface.",
)

GT_CVES = {
    "CVE-2024-24762",
    "CVE-2024-47874",
    "CVE-2025-54121",
    "CVE-2024-53981",
    "CVE-2021-41945",
    "CVE-2024-3772",
    "CVE-2025-71176",
    "CVE-2024-3568",
    "CVE-2024-11394",
    "CVE-2024-22195",
    "CVE-2024-34064",
    "CVE-2023-45803",
    "CVE-2024-37891",
    "CVE-2024-3651",
    "CVE-2025-43859",
    "CVE-2026-63374",
    "CVE-2026-64847",
    "CVE-2024-45811",
    "CVE-2024-45812",
    "CVE-2025-30208",
    "CVE-2026-45623",
    "CVE-2024-55565",
    "CVE-2022-25883",
    "CVE-2024-4068",
    "CVE-2024-4067",
    "CVE-2024-21538",
    "CVE-2023-45133",
    "CVE-2024-47068",
    "GHSA-67mh-4wv8-2f99",
    "CVE-2026-33671",
    "CVE-2026-33672",
}

TOOL_COLS = [
    ("pip-audit", "pip-audit?"),
    ("npm-audit", "npm-audit?"),
    ("Trivy", "Trivy?"),
    ("Grype", "Grype?"),
    ("DepCheck", "DepCheck?"),
]


def main() -> None:
    rows = list(csv.DictReader(SRC.open()))
    out = []
    missing = []
    for r in rows:
        key = (r["CVE_ID"], r["Package"])
        if r["Ecosystem"] == "Go":
            verdict, reach, reason = GO_REASON
        elif key in TRIAGE:
            verdict, reach, reason = TRIAGE[key]
        else:
            missing.append(key)
            verdict, reach, reason = (
                "Uncertain",
                "Unknown",
                "No triage rule recorded.",
            )
        nr = dict(r)
        nr["Verdict"] = verdict
        nr["Reachable?"] = reach
        nr["Reasoning"] = reason
        out.append(nr)

    if missing:
        raise SystemExit(f"missing triage for {missing}")

    fields = list(rows[0].keys()) + ["Verdict", "Reachable?", "Reasoning"]
    for dest in (OUT_RESEARCH, OUT_RESULTS):
        with dest.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(out)

    counts = Counter(r["Verdict"] for r in out)
    print("verdicts", dict(counts), "n", len(out))

    metrics = {"n": len(out), "verdicts": dict(counts), "per_tool": {}}
    print("\nPer-tool FPR and GT detection (unique GT IDs = 31)")
    for tname, col in TOOL_COLS:
        flagged = [r for r in out if r[col] == "Y"]
        tp = sum(1 for r in flagged if r["Verdict"] == "TP")
        fp = sum(1 for r in flagged if r["Verdict"] == "FP")
        unc = sum(1 for r in flagged if r["Verdict"] == "Uncertain")
        denom = tp + fp
        fpr = (fp / denom) if denom else None
        caught = {r["CVE_ID"] for r in flagged} & GT_CVES
        det = len(caught) / len(GT_CVES)
        rec = {
            "flagged": len(flagged),
            "TP": tp,
            "FP": fp,
            "Uncertain": unc,
            "FPR": None if fpr is None else round(fpr, 4),
            "FPR_display": "n/a (no TP/FP findings)" if fpr is None else f"{fp}/{denom} = {fpr:.1%}",
            "GT_detected": len(caught),
            "GT_total": len(GT_CVES),
            "detection_rate": round(det, 4),
            "detection_display": f"{len(caught)}/{len(GT_CVES)} = {det:.1%}",
        }
        metrics["per_tool"][tname] = rec
        print(f"  {tname:12} flagged={len(flagged):3} TP={tp:2} FP={fp:3} U={unc:2}  FPR={rec['FPR_display']:28}  det={rec['detection_display']}")

    (ROOT / "research/triage_summary.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print("wrote", OUT_RESEARCH, OUT_RESULTS)


if __name__ == "__main__":
    main()
