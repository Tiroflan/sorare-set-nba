"""Client Sorare en lecture seule.

Garde-fous :
- aucune authentification (ni jeton, ni cookie, ni mot de passe) : l'API
  n'accepte alors que des lectures de données publiques ;
- toute requête qui n'est pas une lecture (mutation, subscription) est refusée
  avant même d'être envoyée.
"""

import json
import re
import time
import urllib.error
import urllib.request

API_URL = "https://api.sorare.com/graphql"
# Anonyme : 20 appels par minute, on reste en dessous.
MIN_INTERVAL_S = 3.2

_last_call = 0.0


class ComplexityError(Exception):
    pass


def _assert_read_only(query: str) -> None:
    stripped = re.sub(r"#.*", "", query).strip()
    if re.match(r"^(mutation|subscription)\b", stripped, re.IGNORECASE):
        raise PermissionError("Lecture seule : mutation et subscription interdites.")


def gql(query: str, variables: dict | None = None, retries: int = 3) -> dict:
    """Envoie une requête GraphQL de lecture et renvoie `data`."""
    global _last_call
    _assert_read_only(query)
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(retries):
        wait = MIN_INTERVAL_S - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "perso-sorare-reader"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "30")))
                continue
            raise
        errors = payload.get("errors")
        if errors:
            msg = "; ".join(err.get("message", "") for err in errors)
            if "complexity" in msg.lower():
                raise ComplexityError(msg)
            raise RuntimeError(msg)
        return payload["data"]
    raise RuntimeError("Trop de 429, abandon.")
