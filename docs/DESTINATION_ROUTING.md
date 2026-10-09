# Destination Discovery & Gateway Routing v0.1

Local-first, transport-independent destination resolution and route selection for the Aurora Comms Layer.

## Goals

- Resolve destinations without assuming reachability.
- Authenticate gateway capability *claims* (not automatic trust).
- Select expiring, policy-checked routes with failover.
- Keep local mesh fully usable when public connectivity is absent.
- Provide a controlled egress *policy boundary* that is **disabled by default**.

## Non-goals (v0.1)

- BGP or global public routing tables.
- A new IP stack or transparent TUN/TAP forwarding.
- Automatic public-internet transit for every node.
- Unreviewed NAT traversal, arbitrary port forwarding, or firewall mutation.
- A working TCP relay / open proxy (explicitly **not implemented**).
- Mandatory MetaField, TensorGate, Bitcoin, GPU, or cloud dependencies.

## Architecture

```
DestinationResolver  ->  classify / DNS / service / node / content
GatewayRegistry      ->  authenticated advertisements (claims)
RouteManager         ->  candidates, policy, hysteresis, backoff
ConnectionManager    ->  mesh + optional TCP/HTTPS *probe*
EgressGateway        ->  policy authorization only (relay not implemented)
NetworkDiagnostics   ->  read-only /comms/* surfaces
```

Does **not** replace Redis, UDP discovery (port 7379), or CommsLayer heartbeats.

## Verified in v0.1

| Capability | Status |
|---|---|
| Destination classification (IP, hostname, service, node, content, URL, host:port, bracketed IPv6) | Implemented + tested |
| Bounded DNS (thread-pool timeout, no process-wide setdefaulttimeout) | Implemented + tested |
| Cache TTL / expiry | Implemented + tested |
| Gateway HMAC ads + sequence anti-replay | Implemented + tested |
| Route selection with cooldown / failover | Implemented + tested |
| Connection-time policy (deny private/reserved, IPv4-mapped IPv6) | Implemented + tested |
| Probe vs delivery separation (`result_kind`) | Implemented + tested |
| Egress disabled by default; relay listener refused | Implemented + tested |
| Dashboard endpoints `/comms/destinations/resolve`, `/routes`, `/gateways`, `/network/status` | Implemented |
| Local mesh without public internet | Implemented + tested |

## Not implemented / future

- TCP/HTTPS application delivery (only reachability probes)
- Authenticated framed relay / proxy listener
- Global routing, NAT traversal, firewall mutation
- Automatic public transit for every node

## Security

- Gateway ads signed with `AURORA_MESH_SECRET`.
- Expired / replayed sequence numbers rejected.
- Connection-time address validation on **every** candidate and the selected address (DNS rebinding defense).
- Public egress always applies `deny_private` (loopback, RFC1918, CGNAT, link-local, ULA, IPv4-mapped IPv6, documentation ranges) regardless of CIDR/port allow-lists.
- EgressGateway does **not** bind a proxy socket in v0.1.
- Does not modify host firewall or routing tables.
- Diagnostics redact gateway signatures.

## Configuration

All defaults keep routing/egress **off**.

| Variable | Default | Meaning |
|----------|---------|--------|
| `AURORA_DESTINATION_ROUTING_ENABLED` | `0` | Master switch |
| `AURORA_GATEWAY_ADVERTISE_ENABLED` | `0` | Emit gateway ads |
| `AURORA_EGRESS_GATEWAY_ENABLED` | `0` | Policy gate (relay still not implemented) |
| `AURORA_EGRESS_BIND_HOST` | `127.0.0.1` | Reserved for future relay |
| `AURORA_EGRESS_PORT` | `0` | 0 = no listener |
| `AURORA_ROUTE_TTL` | `120` | Candidate lifetime |
| `AURORA_ROUTE_CONNECT_TIMEOUT` | `5` | Seconds |
| `AURORA_ROUTE_MAX_RETRIES` | `2` | Failover attempts |
| `AURORA_EGRESS_ALLOWED_CIDRS` | empty | Optional CIDR allow-list (still denies private) |
| `AURORA_EGRESS_ALLOWED_PORTS` | empty | Optional port allow-list |
| `AURORA_EGRESS_DENY_PRIVATE` | `1` | Always recommended |

## API (dashboard)

Read-only diagnostics (same exposure model as other `/comms/*` endpoints):

- `GET /comms/destinations/resolve?target=...`
- `GET /comms/routes?target=...`
- `GET /comms/gateways`
- `GET /comms/network/status`

`reachable_hint` values describe *candidate availability*, not confirmed application delivery.
