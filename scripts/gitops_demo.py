"""GitOps reconciliation demo (local simulation of what Argo CD does).

Desired state  = gitops/k8s/deployment.yaml in a Git repo (single source of truth)
Live state     = a JSON file standing in for the cluster
Reconciler     = loop that diffs desired vs live and converges live -> desired.

Scenarios shown:
 1. Initial sync from Git
 2. New release: a Git commit changes the image tag -> auto rollout (no kubectl/manual deploy)
 3. Drift: someone edits live state by hand (replicas 3 -> 10) -> self-heal reverts it
 4. Rollback: `git revert` -> cluster follows Git back
Writes evidence/05-gitops.txt
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "gitops", "k8s", "deployment.yaml")
OUT = os.path.join(ROOT, "evidence", "05-gitops.txt")
lines = []


def log(m):
    print(m)
    lines.append(m)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


def read_desired(repo):
    text = open(os.path.join(repo, "deployment.yaml")).read()
    return {
        "image": re.search(r"image:\s*(\S+)", text).group(1),
        "replicas": int(re.search(r"replicas:\s*(\d+)", text).group(1)),
    }


def reconcile(repo, live_path, reason):
    desired = read_desired(repo)
    live = json.load(open(live_path)) if os.path.exists(live_path) else {}
    if live == desired:
        log(f"  [reconcile:{reason}] in sync, nothing to do")
        return
    for k in desired:
        if live.get(k) != desired[k]:
            log(f"  [reconcile:{reason}] DIFF {k}: live={live.get(k)!r} desired={desired[k]!r} -> applying")
    json.dump(desired, open(live_path, "w"))
    log(f"  [reconcile:{reason}] live now == Git ({git(repo, 'rev-parse', '--short', 'HEAD')})")


work = tempfile.mkdtemp()
repo, live = os.path.join(work, "repo"), os.path.join(work, "cluster.json")
os.makedirs(repo)
shutil.copy(MANIFEST, repo)
git(repo, "init", "-q", "-b", "main")
git(repo, "config", "user.email", "ci@example.com")
git(repo, "config", "user.name", "ci")
git(repo, "add", "."); git(repo, "commit", "-qm", "initial desired state")

log("== GitOps reconciliation ==")
log("1) Initial sync")
reconcile(repo, live, "poll")

log("2) New release via Git commit (image tag 1.0.0 -> 2.0.0)")
p = os.path.join(repo, "deployment.yaml")
t = open(p).read().replace("lab4-notes-app:1.0.0", "lab4-notes-app:2.0.0")
open(p, "w").write(t)
git(repo, "commit", "-qam", "release: bump image to 2.0.0")
reconcile(repo, live, "poll")

log("3) Drift: manual change on the cluster (replicas 3 -> 10), nothing committed")
state = json.load(open(live)); state["replicas"] = 10; json.dump(state, open(live, "w"))
log(f"  live (tampered): {json.load(open(live))}")
reconcile(repo, live, "selfHeal")

log("4) Rollback via `git revert HEAD`")
git(repo, "revert", "--no-edit", "HEAD")
reconcile(repo, live, "poll")
log(f"  final live state: {json.load(open(live))}")
log("RESULT: cluster state always converged to Git; every change is an auditable commit.")
log("\nGit history (audit trail):\n" + git(repo, "log", "--oneline"))

with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
shutil.rmtree(work)
