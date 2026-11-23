"""Fetch the app secret from Vault at deploy time using AppRole (short-lived token).
The secret is exported to the process environment only; it is never written to disk or Git,
and it is masked when printed.
Usage: eval "$(python secrets/fetch_secret.py)"   # exports API_TOKEN for the next command
"""
import json
import os
import sys
import urllib.request

ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")


def call(path, payload=None, token=None):
    req = urllib.request.Request(
        f"{ADDR}/v1/{path}", method="POST" if payload else "GET",
        data=json.dumps(payload).encode() if payload else None,
        headers={"X-Vault-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main():
    login = call("auth/approle/login", {"role_id": os.environ["VAULT_ROLE_ID"],
                                        "secret_id": os.environ["VAULT_SECRET_ID"]})
    token = login["auth"]["client_token"]                 # expires in 15 min
    secret = call("secret/data/notes-app", token=token)["data"]["data"]["api-token"]
    print(f"export API_TOKEN='{secret}'")
    print(f"fetched API_TOKEN ({secret[:2]}{'*' * 10}) from Vault", file=sys.stderr)   # masked log


if __name__ == "__main__":
    main()
