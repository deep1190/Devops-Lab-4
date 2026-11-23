# Lab 4: Advanced Deployment Strategies & Enterprise DevOps

A small Flask "notes" app used to demonstrate: disaster recovery, CI/CD test gates, blue-green, canary, GitOps and secret management. The full write-up is in [REPORT.md](REPORT.md).

```
app/            Flask app + Dockerfile
tests/          unit + integration tests (pipeline gates)
.github/        CI/CD workflow
blue-green/     nginx + compose + switch.sh
canary/         nginx split_clients + compose + set_weight.sh
gitops/         Kubernetes manifests + Argo CD Application
secrets/        Vault (dev) compose, setup, fetch script
dr/             backup.sh / restore.sh
scripts/        runnable demos, router, secret scanner
evidence/       captured output of every demo
```

## Quick start
```bash
pip install -r requirements-dev.txt
pytest --cov=app
python scripts/bluegreen_demo.py
python scripts/canary_demo.py bad
python scripts/gitops_demo.py
python scripts/dr_demo.py
python scripts/scan_secrets.py
```
Before using the GitOps files, replace `YOUR_GITHUB_USER` in `gitops/k8s/deployment.yaml` and `gitops/argocd/application.yaml`.
