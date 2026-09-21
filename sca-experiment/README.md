# SCA experiment fixture

Controlled software-supply-chain test project. Dependencies are planted with known CVEs on purpose.

**Do not upgrade, patch, or “fix” versions.**

| Doc | Location |
| --- | --- |
| Phase index | [`../research/README.md`](../research/README.md) |
| Phase 1 design | [`../research/PHASE_1_CONTROLLED_PROJECT.md`](../research/PHASE_1_CONTROLLED_PROJECT.md) |
| Ground truth (CVE table) | [`../research/GROUND_TRUTH.md`](../research/GROUND_TRUTH.md) |
| Realism template | [`../baseline/REAL_PROJECT_PROFILE.md`](../baseline/REAL_PROJECT_PROFILE.md) |

```
sca-experiment/
  backend/     FastAPI (Python, no lockfile)
  frontend/    React + Vite + TypeScript (pnpm-lock.yaml)
```

Backend (from `backend/`):

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8889
```

Frontend (from `frontend/`):

```
pnpm install
pnpm dev
```
