# API

The web app is a client of a REST API, and so can your own scripts: to export results on a schedule, to load
judgments from elsewhere, or to build another front end. The API serves its own interactive reference, generated
from the code, so it is always current:

| Page | Address |
|---|---|
| Interactive reference (Swagger UI), where every call can be tried | <http://localhost:8000/docs> |
| OpenAPI schema | <http://localhost:8000/openapi.json> |

The API listens on the CARA machine only; from elsewhere, reach it through an SSH tunnel
(`ssh -L 8000:localhost:8000 <cara host>`).

## Logging in

Every call except `/auth/token` and `/health` needs a token, sent as a bearer token. A token lasts as long as a
login in the web app (`CARA_TOKEN_MINUTES`).

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/token -d username=admin -d password='<password>' | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/studies
```

## Example: export the consensus qrels

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/studies/<study id>/admin/exports/consensus_qrels > consensus.qrels
```

| Export | Name | Parameter |
|---|---|---|
| One annotator's qrels | `qrels` | `?username=<name>` |
| Consensus qrels | `consensus_qrels` | |
| Training pairs | `pairs` | |
| Action log | `actions` | |

The same permissions apply as in the web app: exports need an admin of the study, and an annotator sees only
their own queries.
