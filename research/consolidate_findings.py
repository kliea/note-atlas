#!/usr/bin/env python3
"""Consolidate SCA scanner results into findings.csv. Raw join only — no FP/FN labels."""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/klinthjeraldmatugas/Documents/DEV/ATLAS")
RESULTS = ROOT / "sca-experiment/results"
OUT_RESEARCH = ROOT / "research/findings.csv"
OUT_RESULTS = ROOT / "sca-experiment/results/findings.csv"

CVE_RE = re.compile(r"CVE-\d{4}-\d+")
GHSA_RE = re.compile(r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}")
PYSEC_RE = re.compile(r"PYSEC-\d{4}-\d+")

TOOLS = ["pip-audit", "npm-audit", "Trivy", "Grype", "DepCheck"]

SEV_RANK = {
    "critical": 4,
    "high": 3,
    "moderate": 2,
    "medium": 2,
    "low": 1,
    "info": 0,
    "unknown": 0,
    "none": 0,
}
SEV_LABEL = {4: "Critical", 3: "High", 2: "Medium", 1: "Low", 0: "Unknown"}


def norm_sev(raw: str | None) -> str:
    if not raw:
        return "Unknown"
    key = str(raw).strip().lower()
    if key in ("moderate", "medium"):
        return "Medium"
    if key in SEV_RANK:
        return SEV_LABEL[SEV_RANK[key]]
    return str(raw).strip().title()


def sev_range(sevs: set[str]) -> str:
    labels = {s for s in sevs if s}
    if not labels:
        return "Unknown"
    if len(labels) == 1:
        return next(iter(labels))
    ranks = sorted({SEV_RANK.get(s.lower(), 0) for s in labels})
    names = [SEV_LABEL.get(r, "Unknown") for r in ranks]
    return f"{names[0]}–{names[-1]}"


def norm_pkg(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return name
    if name.startswith("@"):
        return name
    return name.lower()


def ids_from_text(*parts: str) -> set[str]:
    blob = " ".join(p or "" for p in parts)
    found: set[str] = set()
    found.update(CVE_RE.findall(blob))
    found.update(i.upper().replace("GHSA", "GHSA") for i in GHSA_RE.findall(blob.lower()))
    # normalize GHSA to lowercase body
    ghsa = {m.group(0) for m in GHSA_RE.finditer(blob)}
    found.update(ghsa)
    found.update(PYSEC_RE.findall(blob))
    return found


def parse_purl(purl: str) -> tuple[str, str]:
    """Return (ecosystem, package) from a purl if possible."""
    if not purl or not purl.startswith("pkg:"):
        return "", ""
    body = purl[4:]
    typ, _, rest = body.partition("/")
    rest = rest.split("?")[0].split("#")[0]
    name = rest.split("@")[0]
    name = urllib.parse.unquote(name)
    eco = {"pypi": "PyPI", "npm": "npm", "golang": "Go", "cargo": "crates.io", "maven": "Maven"}.get(
        typ.lower(), typ
    )
    return eco, name


# Ground-truth (CVE_ID, package) pairs from GROUND_TRUTH.md Known CVE column.
GT_PAIRS: set[tuple[str, str]] = set()
GT_ROWS = [
    ("CVE-2024-24762", "fastapi", "PyPI"),
    ("CVE-2024-47874", "starlette", "PyPI"),
    ("CVE-2025-54121", "starlette", "PyPI"),
    ("CVE-2024-24762", "python-multipart", "PyPI"),
    ("CVE-2024-53981", "python-multipart", "PyPI"),
    ("CVE-2021-41945", "httpx", "PyPI"),
    ("CVE-2024-3772", "pydantic", "PyPI"),
    ("CVE-2025-71176", "pytest", "PyPI"),
    ("CVE-2024-3568", "transformers", "PyPI"),
    ("CVE-2024-11394", "transformers", "PyPI"),
    ("CVE-2024-22195", "jinja2", "PyPI"),
    ("CVE-2024-34064", "jinja2", "PyPI"),
    ("CVE-2023-45803", "urllib3", "PyPI"),
    ("CVE-2024-37891", "urllib3", "PyPI"),
    ("CVE-2024-3651", "idna", "PyPI"),
    ("CVE-2025-43859", "h11", "PyPI"),
    ("CVE-2026-63374", "anyio", "PyPI"),
    ("CVE-2026-64847", "anyio", "PyPI"),
    ("CVE-2024-45811", "vite", "npm"),
    ("CVE-2024-45812", "vite", "npm"),
    ("CVE-2025-30208", "vite", "npm"),
    ("CVE-2026-45623", "postcss", "npm"),
    ("CVE-2024-55565", "nanoid", "npm"),
    ("CVE-2022-25883", "semver", "npm"),
    ("CVE-2024-4068", "braces", "npm"),
    ("CVE-2024-4067", "micromatch", "npm"),
    ("CVE-2024-21538", "cross-spawn", "npm"),
    ("CVE-2023-45133", "@babel/traverse", "npm"),
    ("CVE-2024-47068", "rollup", "npm"),
    ("GHSA-67mh-4wv8-2f99", "esbuild", "npm"),
    ("CVE-2026-33671", "picomatch", "npm"),
    ("CVE-2026-33672", "picomatch", "npm"),
]
for cid, pkg, _eco in GT_ROWS:
    GT_PAIRS.add((cid, norm_pkg(pkg)))

# Alias graph: id -> set of equivalent ids
aliases: dict[str, set[str]] = defaultdict(set)


def add_alias(*ids: str) -> None:
    ids = [i for i in ids if i]
    for a in ids:
        aliases[a].update(ids)
        aliases[a].add(a)


def component(id_: str) -> set[str]:
    seen: set[str] = set()
    stack = [id_]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(aliases.get(cur, set()) - seen)
    return seen


def canonical_ids(raw_ids: set[str]) -> list[str]:
    """Prefer CVE IDs; fall back to GHSA; then whatever remains."""
    if not raw_ids:
        return []
    expanded: set[str] = set()
    for i in raw_ids:
        expanded |= component(i)
        expanded.add(i)
    cves = sorted(i for i in expanded if i.startswith("CVE-"))
    if cves:
        return cves
    ghsas = sorted(i for i in expanded if i.startswith("GHSA-"))
    if ghsas:
        return ghsas
    return sorted(expanded)


# rows[(cve, pkg)] -> record
Row = dict
rows: dict[tuple[str, str], dict] = {}


def record(cve: str, pkg: str, eco: str, tool: str, severity: str) -> None:
    pkg_n = norm_pkg(pkg)
    if not cve or not pkg_n:
        return
    key = (cve, pkg_n)
    rec = rows.setdefault(
        key,
        {
            "cve": cve,
            "package": pkg_n,
            "ecosystem": eco or "",
            "sevs": set(),
            "tools": {t: False for t in TOOLS},
        },
    )
    rec["tools"][tool] = True
    rec["sevs"].add(norm_sev(severity))
    if eco and not rec["ecosystem"]:
        rec["ecosystem"] = eco
    # Prefer PyPI/npm over empty/Go if mixed (shouldn't happen often)
    if eco in ("PyPI", "npm") and rec["ecosystem"] not in ("PyPI", "npm"):
        rec["ecosystem"] = eco


def osv_aliases(ghsa_ids: list[str]) -> None:
    for ghsa in ghsa_ids:
        body = json.dumps({"id": ghsa}).encode()
        req = urllib.request.Request(
            "https://api.osv.dev/v1/vulns/" + ghsa,
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            # try query by id via vulns path already; skip on failure
            continue
        ids = {data.get("id", ghsa)}
        ids.update(data.get("aliases") or [])
        add_alias(*[i for i in ids if i])


# --- parse scanners ---

def parse_trivy() -> None:
    data = json.loads((RESULTS / "trivy.json").read_text())
    for result in data.get("Results") or []:
        rtype = (result.get("Type") or "").lower()
        eco = "PyPI" if rtype in ("pip", "python", "pypi") else "npm" if rtype in ("npm", "pnpm", "yarn", "node") else rtype
        for v in result.get("Vulnerabilities") or []:
            vid = v.get("VulnerabilityID") or ""
            pkg = v.get("PkgName") or ""
            if not pkg:
                purl = ((v.get("PkgIdentifier") or {}).get("PURL")) or ""
                eco2, pkg = parse_purl(purl)
                eco = eco or eco2
            found = ids_from_text(vid, " ".join(v.get("VendorIDs") or []), v.get("PrimaryURL") or "")
            if vid:
                found.add(vid)
            add_alias(*found)
            for cid in canonical_ids(found or {vid}):
                record(cid, pkg, eco, "Trivy", v.get("Severity") or "")


def parse_grype() -> None:
    data = json.loads((RESULTS / "grype.json").read_text())
    for m in data.get("matches") or []:
        vuln = m.get("vulnerability") or {}
        art = m.get("artifact") or {}
        pkg = art.get("name") or ""
        lang = (art.get("language") or "").lower()
        typ = (art.get("type") or "").lower()
        eco, pkg_from_purl = parse_purl(art.get("purl") or "")
        if pkg_from_purl:
            pkg = pkg_from_purl
        if not eco:
            if lang == "python" or typ in ("python", "pypi"):
                eco = "PyPI"
            elif lang in ("javascript", "js") or typ in ("npm", "yarn"):
                eco = "npm"
            elif lang == "go" or typ == "go-module":
                eco = "Go"
        found = ids_from_text(vuln.get("id") or "")
        related_ids = []
        for rel in m.get("relatedVulnerabilities") or []:
            rid = rel.get("id") or ""
            if rid:
                related_ids.append(rid)
                found.add(rid)
        if vuln.get("id"):
            found.add(vuln["id"])
        add_alias(vuln.get("id") or "", *related_ids)
        ids = canonical_ids(found)
        if not ids and vuln.get("id"):
            ids = [vuln["id"]]
        for cid in ids:
            record(cid, pkg, eco, "Grype", vuln.get("severity") or "")


def parse_npm() -> None:
    data = json.loads((RESULTS / "npm-audit.json").read_text())
    for pkg, rec in (data.get("vulnerabilities") or {}).items():
        pkg_name = rec.get("name") or pkg
        for via in rec.get("via") or []:
            if not isinstance(via, dict):
                continue
            url = via.get("url") or ""
            found = ids_from_text(url, via.get("title") or "", json.dumps(via))
            if not found:
                # keep GHSA from URL path
                m = GHSA_RE.search(url)
                if m:
                    found.add(m.group(0))
            add_alias(*found)
            ids = canonical_ids(found)
            if not ids:
                continue
            for cid in ids:
                record(cid, pkg_name, "npm", "npm-audit", via.get("severity") or rec.get("severity") or "")


def parse_depcheck() -> None:
    data = json.loads((RESULTS / "depcheck.json").read_text())
    for dep in data.get("dependencies") or []:
        pkg = ""
        eco = ""
        for p in dep.get("packages") or dep.get("packageIds") or []:
            pid = p.get("id") or ""
            e, n = parse_purl(pid)
            if n:
                pkg = n
                eco = e
                break
        if not pkg:
            fn = dep.get("fileName") or ""
            pkg = fn.split(":")[0]
            path = dep.get("filePath") or ""
            if "requirements.txt" in path or "pypi" in path.lower():
                eco = "PyPI"
            elif "package" in path or "pnpm" in path or "node" in path:
                eco = "npm"
        vulns = dep.get("vulnerabilities") or []
        names = [v.get("name") or "" for v in vulns]
        add_alias(*[n for n in names if n.startswith(("CVE-", "GHSA-"))])
        for v in vulns:
            name = v.get("name") or ""
            found = ids_from_text(name, v.get("description") or "", json.dumps(v.get("references") or []))
            if name:
                found.add(name)
            add_alias(*found)
            ids = canonical_ids(found)
            if not ids and name:
                ids = [name]
            for cid in ids:
                record(cid, pkg, eco, "DepCheck", v.get("severity") or "")


def parse_pip_audit() -> int:
    text = (RESULTS / "pip-audit.txt").read_text()
    # Resolution error — no CVE rows.
    return 0 if "ResolutionImpossible" in text or "ERROR" in text else -1


parse_trivy()
parse_grype()
parse_npm()
parse_depcheck()
parse_pip_audit()

# Map leftover GHSAs via OSV so npm GHSA rows merge with CVE rows from other tools.
unmapped_ghsa = sorted(
    {cve for (cve, _pkg) in rows if cve.startswith("GHSA-") and not any(x.startswith("CVE-") for x in component(cve))}
)
if unmapped_ghsa:
    osv_aliases(unmapped_ghsa)
    # rebuild rows with new aliases
    old = list(rows.items())
    rows.clear()
    # Re-parse is cleaner
    aliases  # already updated
    parse_trivy()
    parse_grype()
    parse_npm()
    parse_depcheck()

# After OSV, merge any remaining GHSA row into CVE if now aliased.
merged: dict[tuple[str, str], dict] = {}
for (cid, pkg), rec in rows.items():
    canon = canonical_ids({cid})
    target = canon[0] if canon else cid
    key = (target, pkg)
    if key not in merged:
        merged[key] = rec
        merged[key]["cve"] = target
    else:
        dst = merged[key]
        for t, flag in rec["tools"].items():
            dst["tools"][t] = dst["tools"][t] or flag
        dst["sevs"] |= rec["sevs"]
        if rec["ecosystem"] and not dst["ecosystem"]:
            dst["ecosystem"] = rec["ecosystem"]
rows = merged

# Write CSV
headers = [
    "CVE_ID",
    "Package",
    "Ecosystem",
    "Severity",
    "pip-audit?",
    "npm-audit?",
    "Trivy?",
    "Grype?",
    "DepCheck?",
    "Num_tools_flagged",
    "In_ground_truth?",
]


def yn(v: bool) -> str:
    return "Y" if v else "N"


ordered = sorted(rows.values(), key=lambda r: (r["cve"], r["package"]))
out_rows = []
for rec in ordered:
    n = sum(1 for t in TOOLS if rec["tools"][t])
    gt = yn((rec["cve"], rec["package"]) in GT_PAIRS)
    out_rows.append(
        {
            "CVE_ID": rec["cve"],
            "Package": rec["package"],
            "Ecosystem": rec["ecosystem"] or "",
            "Severity": sev_range(rec["sevs"]),
            "pip-audit?": yn(rec["tools"]["pip-audit"]),
            "npm-audit?": yn(rec["tools"]["npm-audit"]),
            "Trivy?": yn(rec["tools"]["Trivy"]),
            "Grype?": yn(rec["tools"]["Grype"]),
            "DepCheck?": yn(rec["tools"]["DepCheck"]),
            "Num_tools_flagged": n,
            "In_ground_truth?": gt,
        }
    )

for path in (OUT_RESEARCH, OUT_RESULTS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(out_rows)

# Summaries
print(f"ROWS {len(out_rows)}")
print("--- A per-tool ---")
for t, col in [
    ("pip-audit", "pip-audit?"),
    ("npm-audit", "npm-audit?"),
    ("Trivy", "Trivy?"),
    ("Grype", "Grype?"),
    ("DepCheck", "DepCheck?"),
]:
    hits = [r for r in out_rows if r[col] == "Y"]
    gt = sum(1 for r in hits if r["In_ground_truth?"] == "Y")
    print(f"{t}\t{len(hits)}\tgt_pairs_caught={gt}")

print("--- B overlap ---")
from collections import Counter

c = Counter(r["Num_tools_flagged"] for r in out_rows)
for k in range(1, 6):
    print(f"exactly_{k}\t{c.get(k, 0)}")

print("--- C ground truth coverage ---")
print(f"gt_pairs\t{len(GT_PAIRS)}")
caught_any = set()
for t, col in [
    ("pip-audit", "pip-audit?"),
    ("npm-audit", "npm-audit?"),
    ("Trivy", "Trivy?"),
    ("Grype", "Grype?"),
    ("DepCheck", "DepCheck?"),
]:
    caught = {(r["CVE_ID"], r["Package"]) for r in out_rows if r[col] == "Y" and r["In_ground_truth?"] == "Y"}
    missed = GT_PAIRS - caught
    caught_any |= caught
    print(f"{t}\t{len(caught)}/{len(GT_PAIRS)}")
    if missed and t != "pip-audit":
        pass
print(f"union\t{len(caught_any)}/{len(GT_PAIRS)}")
missed_all = GT_PAIRS - caught_any
print("missed_all", sorted(missed_all)[:40], "count", len(missed_all))

# JSON sidecar for canvas
summary = {
    "n_rows": len(out_rows),
    "per_tool": {},
    "overlap": {str(k): c.get(k, 0) for k in range(1, 6)},
    "gt_total": len(GT_PAIRS),
    "gt_caught": {},
    "gt_missed": sorted(f"{a}|{b}" for a, b in missed_all),
}
for t, col in [
    ("pip-audit", "pip-audit?"),
    ("npm-audit", "npm-audit?"),
    ("Trivy", "Trivy?"),
    ("Grype", "Grype?"),
    ("DepCheck", "DepCheck?"),
]:
    hits = [r for r in out_rows if r[col] == "Y"]
    caught = {(r["CVE_ID"], r["Package"]) for r in hits if r["In_ground_truth?"] == "Y"}
    summary["per_tool"][t] = {
        "rows": len(hits),
        "gt_pairs": len(caught),
    }
    summary["gt_caught"][t] = len(caught)

(ROOT / "research/findings_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print("wrote", OUT_RESEARCH, OUT_RESULTS)
