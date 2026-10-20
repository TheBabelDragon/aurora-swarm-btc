# Aurora HTTPS Viewer

Secure **destination-access control plane** integrated with the dashboard and
destination-routing architecture. It is **not** an unrestricted network proxy
and does **not** embed arbitrary remote pages in the dashboard origin.

## Architecture decision

The dashboard is a conventional **FastAPI** web application (`dashboard/run.py`).
It does not ship an embedded Chromium/Electron runtime. Therefore:

| Approach | Status |
|----------|--------|
| Iframe embedding of arbitrary HTTPS sites | **Not supported** |
| Dashboard fetches and rewrites remote HTML | **Not implemented** |
| Viewer session + URL/policy API | **Implemented** |
| Loopback HTTP CONNECT proxy for external browsers | **Optional** (`AURORA_VIEWER_PROXY_ENABLED=1`) |
| TLS termination / certificate disablement | **Never** |

## API (`aurora.viewer.v1`)

| Method | Path | Purpose |
|--------|------|--------|
| GET | `/comms/viewer/status` | Capabilities |
| POST | `/comms/viewer/sessions` | Create session |
| GET | `/comms/viewer/sessions/{id}` | Session state |
| POST | `/comms/viewer/sessions/{id}/navigate` | Evaluate HTTPS URL + route policy |
| POST | `/comms/viewer/sessions/{id}/cancel` | Cancel |
| DELETE | `/comms/viewer/sessions/{id}` | Close |
| GET | `/comms/viewer/sessions/{id}/diagnostics` | Safe diagnostics |

Navigate does **not** download page bodies.

## Security

- Only `https://` absolute URLs; no embedded credentials.
- Blocks loopback, private, metadata, reserved addresses; control-plane ports.
- Connection-time DNS validation (rebinding defense).
- Public egress disabled by default.
- CONNECT proxy binds loopback only.

## Tests

```bash
python -m pytest tests/test_https_viewer.py tests/test_destination_routing.py -q
```

## Limitations

No in-dashboard unrestricted browser. Mesh routes are not a transparent TCP
tunnel for arbitrary HTTPS unless a future authorized relay is implemented.
