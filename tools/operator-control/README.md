# Operator Control Reference

This directory contains an executable, test-local policy broker core. It does not create an OS user, install a service, open a listener, or connect an account.

## Boundary

The model-facing plugin is disabled by default. `pre_tool_call` is defense in depth because Hermes 0.21 callback exceptions may fail open. Every supported write handler must call `ActionBroker.execute`; it performs the authoritative approval check after entering the handler and before invoking the provider callback.

The broker resolves requester, executor, credential principal, recipient, approver, evidence collector, reviewer, accepter, and exception authority from a trusted identity service. Every overlap is denied unless the protected resolver returns that exact role pair in `allowed_overlaps`. `authority_type` is exactly `one_off` or `standing`; authority is never inferred. Scope binds action, account, target, canonical material-payload digest, limits, task/requirement versions, protected policy digest, expiry, operation key, cancellation, and non-transferability.

There is no generic record-write API. Bootstrap policy assets are imported once into broker-owned, content-addressed, HMAC-signed SQLite records. The source files have no effect authority after import. Authenticated policy-authority `publish_policy`/`update_policy` calls create a new immutable version and atomically move the current pointer; `import_policy` detects source drift without publishing it. Old versions are never overwritten, and only a non-current version may be revoked. Evidence is issued only from a collector that opened the retained source, returns its bytes, and supplies a protected, criterion-bound verifier result. Reviews, exceptions, and acceptances each use their own authenticated resolver/channel; actor identities in payloads are ignored or rejected. Model-facing callers can submit identifiers and evidence collection requests, but cannot supply or sign protected record bodies.

Unknown routes and broker failures deny. Intent precedes dispatch. `ActionBroker.execute` holds one cross-process SQLite `BEGIN IMMEDIATE` transaction while it selects and verifies the current signed policy, validates acceptance and approval, reserves dispatch, invokes the supported adapter, and commits the effect fence. Every policy publish/update/revoke uses the same writer lock. Therefore an update committed before reservation governs and blocks stale authority; an update attempted after reservation waits for the effect commit and applies only to future operations. Approval revocation uses the same database lock and is denied once dispatch has been reserved. Confirmed success requires provider ID and bound readback. Only the seven required binding fields are returned or persisted; extra fields such as `customer_note` are discarded, and secret-like fields or values recursively fail closed. A possible-success timeout is persisted as `unknown`; retry is denied until reconciliation.

## Deployment

Tests load this broker in process only. Consequential production writes require a separate UID/container or managed policy service, owner/ACL-restricted Unix IPC, independently protected policy/signing state, and adapter-specific live tests. No such boundary is configured by this distribution.

The bundled SQLite store is security metadata only, not a task store. It is schema version 4 and contains signed broker-owned approval, acceptance, evidence, review, policy-authority, policy, and exception records. The managed budget ledger stores reservations only; canonical task/run/claim/profile/workspace/client context remains in native Kanban. Before migration, create and verify a private backup. Rollback blocks new work and refuses while pending or unknown effects remain; then disable IPC, revoke client access, restore compatible code/store, and test denial plus one approved synthetic operation.

## Unsupported coverage

Generic terminal/browser writes and direct Kanban dashboard/CLI transitions are not gated. Kanban observation is record-only on Hermes 0.21 and cannot veto native transitions or early parent promotion. Keep acceptance-sensitive auto-release manual/blocked unless a supported protected route rechecks signed acceptance.
