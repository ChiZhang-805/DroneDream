# DroneDream project context

Read `docs/PROJECT_MEMORY.md` before product, UI, mission, acceptance, or release
work. On this workstation also read the shared principles at
`Q:\DroneDream-Workspace\Documents\DRONEDREAM_AGENT_CORE_PRODUCT_PRINCIPLES.md`.

The user expects ordinary, incomplete natural language such as “帮我拿个东西”.
The Agent must use context and tools, ask concise questions for missing essential
information, and produce a complete confirmable mission. Do not require users to
specify aircraft IDs, map IDs, flight heights, exact routes, tool names, or every
takeoff/return step. A scripted takeoff/hover/landing smoke test does not establish
natural-language Agent acceptance.

User-facing explanations must distinguish requested capabilities from verified
implementation. Preserve these requirements across chats and update the existing
memory when the user corrects them.
