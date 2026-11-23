# Lab 4 Report: Advanced Deployment Strategies & Enterprise DevOps

**Application:** `notes-app` (Flask + SQLite) with `/health`, `/version`, `GET/POST /notes`
**Repo layout:** see `README.md`. All evidence files are in `evidence/`.

---

## 1. Summary

| # | Task | Where | Evidence |
|---|------|-------|----------|
| 1 | Disaster recovery | `dr/`, `scripts/dr_demo.py` | `evidence/02-disaster-recovery.txt` |
| 2 | Automated tests as pipeline gates | `tests/`, `.github/workflows/ci-cd.yml` | `evidence/01-test-run.txt`, `06-pipeline-gates-and-secrets.txt` |
| 3 | Blue-Green | `blue-green/`, `scripts/bluegreen_demo.py` | `evidence/03-bluegreen.txt` |
| 4 | GitOps | `gitops/`, `scripts/gitops_demo.py` | `evidence/05-gitops.txt` |
| 5 | This report | `REPORT.md` | n/a |
| 6 | Secret management | `secrets/`, `scripts/scan_secrets.py` | `evidence/06-pipeline-gates-and-secrets.txt` |
| 7 | Canary | `canary/`, `scripts/canary_demo.py` | `evidence/04-canary-bad.txt`, `04-canary-good.txt` |

**How the demos were run.** The behaviour demos start real `gunicorn` instances of the app. A small Python reverse proxy (`scripts/router.py`) plays the role of nginx so the demos run anywhere. The production-style configs (nginx, Docker Compose, Kubernetes, Argo CD, Vault) are included for the real deployment. They are the same logic, but the sandbox used to build this had no Docker daemon, so those specific files were syntax-checked (YAML parses) and **not executed**. See section 9 for the commands to run them on your own machine.

---

## 2. Disaster Recovery (5 marks)

**Design**
- **Backup:** `dr/backup.sh` uses the SQLite online backup API (consistent copy while the app runs) and writes a SHA-256 checksum next to each backup.
- **Restore:** `dr/restore.sh` verifies the checksum first (refuses corrupt/tampered backups), copies the backup into place, then runs `PRAGMA integrity_check`.
- **Failover:** a standby instance is started from the restored data on a different port; traffic is pointed at it.

**Recovery objectives (documented targets)**
- **RTO** (how fast we are back): 60 seconds
- **RPO** (how much data we may lose): 5 minutes, i.e. backup every 5 minutes (cron/CI schedule)

**Observations (from `evidence/02-disaster-recovery.txt`)**
- Primary was killed and its database file deleted.
- Standby came up from the backup in **0.26 s** (target 60 s: met).
- **5 of 7 notes recovered.** The 2 notes written after the last backup were lost. This shows RPO is decided by backup frequency, not by restore speed.
- A tampered backup was **rejected** (exit code 1), so we never restore corrupt data silently.

**Limits and improvements:** a single-node backup is not high availability. For a smaller RPO use continuous replication (e.g. Litestream, or PostgreSQL streaming replication). Store backups off-site (object storage) and test restores on a schedule.

---

## 3. Automated Testing in CI/CD (5 marks)

Pipeline (`.github/workflows/ci-cd.yml`), each job `needs:` the previous one, so a failure stops everything after it:

```
secret-scan -> unit-tests -> integration-tests -> build-image -> deploy-gitops
```

- **Unit tests** (`tests/test_unit.py`, 7 tests): endpoints in isolation, validation, auth token, simulated failure.
- **Integration tests** (`tests/test_integration.py`, 3 tests): app plus a real SQLite file (round trip, persistence, ordering).
- **Quality gate:** whole suite must keep **>= 90 % coverage** (`--cov-fail-under=90`). Actual: **97.87 %**, 10/10 tests pass.
- **Gate proof:** `evidence/06-...txt` shows a deliberately broken change failing the unit gate with exit code 1, which is what blocks `build-image` and `deploy-gitops` in CI. After the fix the gates pass.
- Images are only built and deployed from `main`, never from pull requests.

---

## 4. Blue-Green Deployment (5 marks)

**Implementation:** two identical environments (blue = live v1.0.0, green = idle v2.0.0) behind one router. `blue-green/switch.sh` health-checks the target, rewrites `active.conf`, validates (`nginx -t`) and does a graceful `nginx -s reload`, then smoke-tests.

**Demo result (`evidence/03-bluegreen.txt`):** a client sent requests continuously (~100 per second) while traffic was cut over from blue to green and then rolled back.

| Metric | Result |
|---|---|
| Requests during test | 335 |
| Failed requests | **0** |
| Version before switch / after switch / after rollback | 1.0.0 / 2.0.0 / 1.0.0 |

**Advantages**
- Instant cutover and **instant rollback** (flip back to blue, which is still running).
- Full pre-production testing of green in a production-identical environment.
- No mixed versions: all users see either old or new.

**Limitations**
- Needs **double the infrastructure** while both run.
- **Database changes** are hard: both versions share one database, so schema changes must be backward compatible (expand/contract pattern).
- All users switch at once, so a bug hits 100 % of users (canary reduces this).
- In-flight sessions or caches may need handling at the switch.

---

## 5. Canary Deployment (5 marks)

**Implementation:** stable v1.0.0 plus canary v2.0.0. Traffic is increased in steps **5 % -> 25 % -> 50 % -> 100 %**. After each step a controller reads canary metrics and decides continue, promote or roll back (`canary/` has the nginx `split_clients` version; `scripts/canary_demo.py` is the runnable controller).

**Rollback triggers:** canary 5xx error rate **> 5 %**, or average latency **> 500 ms**.

**Results**

| Scenario | Step reached | Canary error rate | Decision |
|---|---|---|---|
| Faulty v2 (30 % failures injected) | 5 % (15 requests) | **46.7 %** | **Rolled back automatically**, only ~5 % of users touched |
| Healthy v2 | 5, 25, 50, 100 % | 0.0 % at every step | **Promoted** to 100 % |

(From `evidence/04-canary-bad.txt` and `04-canary-good.txt`.)

**Analysis:** the bad release was caught in the first step, so the blast radius was about 5 % of traffic instead of 100 %. Limitation: with low traffic a small canary slice gives too few samples to be statistically meaningful, so step duration and minimum request counts matter.

---

## 6. GitOps (5 marks)

**Implementation:** Git is the single source of truth. `gitops/k8s/` holds declarative Kubernetes manifests; `gitops/argocd/application.yaml` tells Argo CD to watch the repo with `automated: {prune: true, selfHeal: true}`. CI never runs `kubectl`; it only commits a new image tag, and the controller reconciles.

**Reconciliation demo (`evidence/05-gitops.txt`)**
1. Initial sync: cluster empty, so it is created from Git.
2. Commit "bump image to 2.0.0": the live state **automatically** became 2.0.0.
3. **Drift:** someone manually set replicas 3 -> 10; the reconciler detected it and **reverted to 3** (self-heal).
4. `git revert`: the cluster followed Git back to 1.0.0.
5. The Git log is a full audit trail of every change.

---

## 7. Secret Management (5 marks)

- **Store:** HashiCorp Vault (`secrets/docker-compose.vault.yml`, KV v2 at `secret/notes-app`). The secret is **generated randomly** by `vault_setup.sh`, never typed into a file.
- **Least privilege:** policy `notes-app-read` allows read of only that one path.
- **Short-lived access:** the pipeline uses **AppRole**, tokens expire after 15 minutes. `secrets/fetch_secret.py` logs in, reads the secret into an environment variable only (nothing written to disk) and masks it in logs.
- **In the app:** `API_TOKEN` is read from the environment, never hard-coded. In Kubernetes it comes from a Secret (`secretKeyRef`), populated from Vault (e.g. External Secrets Operator), so no secret is in Git.
- **Prevention gate:** `scripts/scan_secrets.py` runs first in CI and fails the build if credentials are committed. Self-test proves it detects a planted secret; the repo scan is clean (`evidence/06-...txt`).
- `.gitignore` excludes `.env`; `.env.example` has only placeholders.

**Limits:** Vault dev mode is in-memory and for the lab only. Production needs real unsealing, TLS, audit logging and rotation. GitHub Actions encrypted secrets are acceptable for the AppRole `role_id`/`secret_id` bootstrap.

---

## 8. Comparison and Risk Analysis (10 marks)

### 8.1 Strategy comparison

| Criterion | Blue-Green | Canary | GitOps | Secret management | Disaster recovery |
|---|---|---|---|---|---|
| **Purpose** | Safe, instant release switch | Gradual, metric-driven release | Declarative, auditable delivery | Protect credentials | Survive outages and data loss |
| **Blast radius of a bad change** | 100 % of users (but instantly reversible) | Small (5 % in our demo) | Whatever Git says; reverted by `git revert` | Leak exposes everything the secret guards | Not applicable |
| **Rollback speed** | Seconds (flip router) | Seconds (set weight 0) | Minutes (revert commit, reconcile) | Rotate secret | RTO measured: 0.26 s demo |
| **Extra cost** | 2x environments | Slightly more than 1x | Controller + Git | Vault service | Backup storage, standby |
| **Complexity** | Low-medium | Medium-high (needs metrics) | Medium | Medium | Medium |
| **Main weakness** | DB schema compatibility, cost | Needs enough traffic and good metrics | Secrets must live outside Git | Vault itself must be protected and available | RPO data loss between backups |
| **Evidence here** | 0 failed of 335 requests | Faulty release stopped at 5 % | Drift reverted, rollback via Git | Scanner clean, short-lived tokens | 5 of 7 notes, tamper rejected |

### 8.2 Risk register

| Risk | Likelihood | Impact | Mitigation in this project |
|---|---|---|---|
| Bad release reaches all users | Medium | High | Canary with auto-rollback; blue-green instant rollback |
| Untested code deployed | Medium | High | Test gates; build/deploy need tests to pass; 90 % coverage floor |
| Secret committed to Git | Medium | High | Secret scan gate, `.gitignore`, Vault, no secrets in manifests |
| Long-lived leaked token | Low | High | AppRole tokens expire in 15 min, least-privilege policy |
| Manual change causes config drift | Medium | Medium | GitOps self-heal reverts drift |
| Data loss / server failure | Low | High | Verified backups, restore with checksum, standby failover |
| Corrupted backup restored | Low | High | SHA-256 verification before restore |
| Backup gap loses recent data | Medium | Medium | Documented RPO; shorten interval or add replication |
| Breaking DB schema change during blue-green | Medium | High | Backward-compatible (expand/contract) migrations |
| Canary has too little traffic to judge | Medium | Medium | Minimum request counts per step; longer steps |

### 8.3 How they combine
They are complementary, not alternatives. A mature flow is: **tests gate the commit -> GitOps delivers it -> canary (or blue-green) limits the risk of the rollout -> secrets come from Vault -> DR protects the data if everything else fails.**

---

## 9. Reproducing on your own machine

```bash
pip install -r requirements-dev.txt
pytest --cov=app                                   # tests
python scripts/dr_demo.py                          # disaster recovery
python scripts/bluegreen_demo.py                   # blue-green
python scripts/canary_demo.py bad                  # canary rollback
python scripts/canary_demo.py good                 # canary promote
python scripts/gitops_demo.py                      # gitops reconcile
python scripts/scan_secrets.py                     # secret scan

# Real nginx/Docker versions (needs Docker)
export API_TOKEN=$(openssl rand -hex 16)
cd blue-green && docker compose up -d --build && ./switch.sh green
cd ../canary  && docker compose up -d --build && ./set_weight.sh 10
cd ../secrets && docker compose -f docker-compose.vault.yml up -d && ./vault_setup.sh
```
For Argo CD: install it on a cluster (e.g. `kind`), edit `repoURL` in `gitops/argocd/application.yaml`, then `kubectl apply -f gitops/argocd/application.yaml`. Take screenshots of these runs for your submission if the lab asks for live evidence.

---

## 10. Conclusions

1. Automated gates are the cheapest risk reduction: they stop broken code before any deployment strategy matters.
2. **Blue-green** gave zero-downtime switching and instant rollback, at the cost of duplicate infrastructure and database-compatibility rules.
3. **Canary** gave the smallest blast radius: a faulty release was stopped at 5 % of traffic, automatically.
4. **GitOps** removes manual deploys and drift, and turns Git history into the audit log and rollback mechanism.
5. **Secret management** works best as prevention (scanner, no secrets in Git) plus short-lived, least-privilege access (Vault AppRole).
6. **Disaster recovery** only counts if restores are tested: our demo proved RTO is easy to meet but RPO depends on backup frequency, so critical data needs replication.
