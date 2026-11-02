# DroneDream · AGENT manual acceptance

This checklist starts after the signed Windows installer has been installed. It
tests the user-visible workflow without requiring a developer terminal or
deleting existing conversations.

## Before the mission

1. Open **DroneDream · AGENT** and sign in. The window title must contain only
   the product name.
2. Open **Maps**. Exactly one bundled map, **Kumpula Campus / 赫尔辛基大学昆普拉校区**,
   must appear. No retired generic map cards or separate 3D-corridor card may be
   visible. Double-click the Kumpula card to inspect its information and
   interactive exterior 3D view. The scene must report its real-world coordinate
   reference, outdoor-only scope, collision geometry, bilingual semantic places,
   and qualified runtime binding without claiming that building interiors exist.
3. Open **Aircraft**. The bundled catalog must expose the qualified **X500 Depth**
   PX4 vehicle used by the Kumpula mission. Its details must identify the flight
   controller, inertial and position sensors, depth camera, collision geometry,
   payload interface, spawn binding, source revision, license, and readiness.
4. Return to **Chatbot**. Start a new conversation and select **X500 Depth** and
   **Kumpula Campus** if they are not already attached. The app performs
   compatibility analysis automatically and must not show a separate
   pair-qualification panel.

## Kumpula delivery round trip

### Natural language is the acceptance input

Begin a separate conversation with:

> 帮我拿个东西。

The Agent should recognize the pickup intent, use available context, and ask
brief natural questions for essential missing facts, such as the place and item.
It must not invent them or require aircraft IDs, map IDs, coordinates, flight
heights, hover durations, tool names, or a complete flight script. Reply with
ordinary words using actual places offered by the map. The Agent must carry
those answers into the same mission and produce a confirmable plan.

The following delivery case checks a natural destination with an implicit
departure and return workflow. The user is not responsible for spelling out
those flight phases. A precise takeoff/hover/land smoke test does not replace
this acceptance.

1. Start a new conversation and send:

   > 帮我把这个小包裹送到信息科学楼。

2. While preparation is running, verify that the visible status changes between
   concrete stages and streams useful progress summaries. It must not expose a
   hidden model chain of thought, stay on an unexplained three-dot indicator, or
   fabricate completed work.
3. The destination must resolve through map semantics to a real usable place at
   **Exactum / 信息科学楼**, such as its qualified outdoor delivery zone. If several
   places are plausible, ask a concise clarification instead of hard-coding one.
   If the destination is deliberately omitted in a second test, verify that the
   assistant asks one natural Chinese question and offers the known Kumpula
   delivery places plus **其他**. Choosing **其他** must reveal an input field.
   Internal field names and error codes must not be shown. The application, not
   the user, supplies the launch, handoff, return and plan-before-execution flow.
4. Verify that the conversation title and plan are in Chinese. The plan card
   must contain the selected aircraft, map, route and ordered execution steps.
5. Click **开始仿真**. The application must acknowledge the command and keep
   **查看运行** disabled until a real live frame is available.
6. In **查看运行**, observe takeoff from the actual launch location in the confirmed
   plan, three-dimensional
   outdoor routing around the qualified collision volumes, arrival and handoff
   at the agreed usable place for **信息科学楼**, return flight, and landing. The current qualified
   map is exterior-only, so this acceptance run must not claim corridor, door,
   stair, or indoor-room traversal.

## Behaviour under incomplete information

- A short model delay or a non-critical missing observation must not abort the
  mission. The bounded fallback controller should slow down and follow the
  latest qualified corridor and pose estimate, then hand control back after the
  learned controller recovers.
- Loss of immediate clearance, state-estimation validity, flight-control link,
  or a safe stopping envelope remains safety critical. The aircraft must hold,
  re-plan, return, or land according to the recorded reason rather than continue
  blindly.
- A moving person or vehicle should produce a local slow/hold/re-plan decision;
  it must not silently rewrite the global mission or treat the original route as
  proof that the path is still clear.

## Acceptance evidence

The run passes only when **Run History** records the same mission identity,
aircraft/map content identities, route, control handoffs, sensor freshness,
payload state, collision result and final landing state seen during the live
run. A generic `EXECUTION_PROCESS_FAILED` banner without the typed root cause is
not an acceptable result.

Do not delete the conversation after a failure. Its run record is the evidence
needed to distinguish an installation/runtime problem from localization,
planning, sensing or control behaviour.
