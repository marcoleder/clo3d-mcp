# Transport and option-handling follow-up

This addresses the five remaining findings against `d0aeb7f` on
`fix/correctness-audit`, in [the fork's PR #1](https://github.com/marcoleder/clo3d-mcp/pull/1).

| Finding | Resolution |
|---|---|
| Command loop exits after a failed review-marker write | Establish the mutation block in memory before attempting disk persistence. Catch marker-write failures and command-loop exceptions. Keep serving when possible, without replaying a claimed command. Preserve its `.working` file until the review marker can be saved or recovery is verified. |
| Cross-process wall-clock expiry | Protocol 3 sends relative durations. Client and bridge use only their own monotonic clocks. A bridge claim requires a fresh client acknowledgement before dispatch, so an abandoned queued request cannot gain a new execution window merely because it was picked up late. |
| Orphan responses and claims accumulate | Under the consumer lock, clean previous-session responses, requests and acknowledgements before publishing readiness. Abandoned claims first establish a persistent scene-review block; if that write fails, retain them as durable evidence and block mutations in memory. Locked files are handled without aborting startup cleanup. |
| Empty rejected-options plumbing | Native option builders return a handle or raise; native exports return paths. Remove the unused list and `rejected_options` response field. Unknown options remain errors before export, and allocated handles are freed on failure. |
| Duplicated Python option application | Share `_apply_options` between model export options and tech pack options. Both reject unknown attributes before entering the export API. |

## Protocol 3 timing and failure semantics

1. The client publishes one session-scoped request containing `timeout_seconds`.
2. The bridge claims it, starts a local monotonic acknowledgement deadline, and
   publishes a random token. This waiting period is capped at five seconds.
3. A client that is still within its own deadline acknowledges that token and
   supplies its remaining duration. The bridge conservatively anchors this
   duration to its earlier claim time and checks it before dispatch.
4. The bridge forgets the dispatchable claim **before** calling CLO or writing
   the final response. Exceptions and failed writes cannot replay that command.

Clock values never cross the process boundary. File modification times are only
best-effort ordering hints, never expiry evidence. A client timeout removes its
pending request/acknowledgement when possible. Once dispatch has begun, native
calls remain non-preemptible and a timeout can still mean an unknown outcome.
Clients and bridge must both be restarted after upgrading from protocol 2.

If the filesystem remains unwritable, no file-based transport can guarantee
delivery of a response. The bridge retains its in-memory block, retries marker
persistence, and preserves the already-written claim for restart recovery. It
does not pretend the failed response was delivered. Reads and explicit shutdown
remain available when the filesystem permits their requests/responses.

## Verification

- **114 offline tests passed**, including ENOSPC/EACCES/EBUSY review writes,
  simultaneous marker and response write failures, continued bridge service,
  no replay, abandoned-claim recovery, startup cleanup, independent clock
  origins, expired acknowledgements and a queued timeout behind a long call.
- All five native export handlers are tested with the simplified wrapper
  return contract. Both Python option routes reject unknown keys before export.
- Static verifier: **48/48 parameter mappings and 84 call sites**.
- Live protocol 3 on **CLO 2026.1.224 / macOS arm64: 48/48 tools, 52 successful
  calls, zero failures**. Native OBJ options, FBX/GLB/glTF and tech pack passed
  with the simplified return contract. The harness verified project identity
  before editing and checked restoration against its original scene baseline.
  The bridge and dialog watcher were stopped afterward.

Evidence is preserved outside Git in
`/Users/port/Documents/gh/clo3d-mcp-live-2026-09-22/`: `transport-suite.log`,
`transport-watcher.log` and `transport-run/` (JSON results, original backup,
test garment and 170 output files). Disk faults and clock drift were injected
offline; actual WSL/Windows behavior remains untested.
