# C++ bridge feasibility notes

Updated after the correctness audit of 2026-09-22. This is a proposal, not a
claim that a persistent Qt bridge has been implemented or validated.

## Verified baseline

The current implementation uses an MCP server, a blocking Python loop inside
CLO, and an optional C ABI shim for exports whose option structures cannot be
constructed through the observed CLO 2026.1.224 Python bindings. Native OBJ
options, FBX, GLB, glTF and tech pack exports produced artifacts in the audit.
The original claim that all tools worked was incorrect: avatar import used the
wrong API and turntable export returned an empty list. See the
[original audit](correctness-audit-2026-09-22.md) and the README for current status.

The transport now uses protocol 3: session readiness metadata, separate files
for each request and response, fresh client acknowledgement and relative
durations checked against local monotonic clocks before dispatch, and one
consumer protected by an OS lock. Clients publish a command once. A timeout or
process crash can leave its outcome unknown; retrying a mutation automatically
is unsafe. A C++ replacement must preserve these properties and must not
restore the old shared request.json/response.json protocol.

## What a timer might improve

A QTimer callback could poll the queue on CLO's main thread while allowing the
normal event loop to run between requests. First build a minimal plugin that
installs a timer, returns from its menu action, and answers ping. Confirm that
the timer and its owning object survive and that CLO remains interactive while
idle. This has not been demonstrated.

A timer does **not** make synchronous simulation, export, or modal API calls
nonblocking. Stop requests and deadlines still cannot interrupt those calls.
The current Python loop releases CLO only on explicit stop or a deadline
checked between commands; MCP client exit does not stop a shared bridge.

No callable Python timer/idle hook or bundled PySide installation was found in
the inspected build. That search does not prove that every possible Python
integration approach is impossible.

## Binding and ABI evidence

SDK headers describe C++ signatures. Binary strings suggest names to inspect;
they do not prove Python registration or constructibility. Comparing counts of
Python attributes and C++ declarations cannot establish equivalent API coverage.
Use live introspection and real calls to establish the particular capabilities
needed for a port. The static verifier does not generate an api_map2.json file.

CLO in this audit bundles Qt 6.10.3; the local Homebrew Qt headers are 6.11.2.
Finding all required symbols in the runtime is useful but is not proof of C++
ABI compatibility. Prefer matching headers and build settings, then test loading,
object lifetime, shutdown and repeated menu invocations. The export shim itself
does not use Qt. Its default macOS deployment target is 15.0, matching the
inspected 2026.1 SDK library; CLO.app's minimum OS metadata alone is insufficient
to choose the shim's minimum supported OS. Windows builds and loading still need
validation on Windows.

## Port acceptance criteria

- Preserve tool schemas, actual return-value checks and explicit option failures.
- Keep CLO calls on the required application thread; reject multiple queue consumers.
- Test simultaneous MCP clients, expired queued commands, restart during a request,
  and a mutation that completes after the client times out. Do not replay it.
- Discover coverage from tools/list. Verify state changes and output artifacts;
  a transport success response alone is insufficient.
- Confirm stop, timer cleanup and plugin unload behavior. A native crash can bring
  down CLO; exception handling cannot contain every native failure.
- Test on supported operating systems and architectures. Keep the Python bridge
  available while comparing behavior on disposable project copies.

A C++ port should proceed only after the timer lifetime experiment demonstrates
the intended idle interactivity. Export availability alone no longer requires a
full port because the existing shim provides those calls.
