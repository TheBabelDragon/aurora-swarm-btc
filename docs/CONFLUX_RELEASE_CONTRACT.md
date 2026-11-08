# Conflux Release Contract (v0.1.1)

Releases are **immutable**. Promotion updates status fields; identity `content_hash` is fixed at creation.

Statuses: candidate → verified → promoted | superseded | revoked

Promotion gates check build success when a build_id is present.

Never mutate an existing release to represent a new release — create a new release and optionally supersede.
