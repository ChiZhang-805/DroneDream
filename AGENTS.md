# DroneDream project context

Read `docs/product/PROJECT_MEMORY.md` before product, UI, mission, acceptance, or
release work, and the shared principles in `docs/product/product-principles.md`.
The only normal source checkouts are this repository and the sibling
`Agent-Core` repository. Update these in place; do not create dated, audit, or
per-task copies of the application. Retired workspace material belongs in the
single workspace `Pending-User-Deletion` directory and is not a build input.
Keep check results in the conversation; do not create audit or scan reports.

Keep `main` as the authoritative integrated product source. Preserve the small
top-level layout documented in `README.md`; do not create per-edition source
trees because Universal, SIM, LAB, FIELD, and AGENT differ through manifests,
branding, capabilities, and build inputs. Do not add fail-fast guards whose
only purpose is to terminate trusted internal flow. Add a rejecting boundary
only when it protects external input, security, account isolation, user data,
release integrity, or flight safety; use ordinary branching for real choices.

The user expects ordinary, incomplete natural language such as “帮我拿个东西”.
The Agent must use context and tools, ask concise questions for missing essential
information, and produce a complete confirmable mission. Do not require users to
specify aircraft IDs, map IDs, flight heights, exact routes, tool names, or every
takeoff/return step. A scripted takeoff/hover/landing smoke test does not establish
natural-language Agent acceptance.

User-facing explanations must distinguish requested capabilities from verified
implementation. Preserve these requirements across chats and update the existing
memory when the user corrects them.
