# DroneDream · AGENT manual acceptance

This checklist starts after the signed Windows installer has been installed. It
tests the user-visible workflow without requiring a developer terminal or
deleting existing conversations.

## Before the mission

1. Open **DroneDream · AGENT** and sign in. The window title must contain only
   the product name.
2. Open **Maps**. Exactly eight bundled 3D maps must appear as scene cards, each
   with its own oblique 3D preview and one concise name. Double-click a card to
   inspect its information and interactive 3D view. Importing or updating a user
   map must create a content identity; an unchanged map must reuse its existing
   analysis, while a changed map must invalidate only the affected compatibility
   result.
3. Open **Aircraft**. The default resource catalog must list the reviewed PX4
   aircraft. Selecting a resource must show its sensors, nested model
   dependencies, recommended tasks, excluded tasks, pinned source revision,
   license, and readiness. Preparing an on-demand model must add the resulting
   asset version to the account library without restarting the application.
4. Return to **Chatbot**. The initial page must contain no old messages. Use the
   plus menu to choose an aircraft and a map. Nothing is selected by default;
   after either item is chosen, the other menu must show only compatible items.
   The app performs compatibility analysis automatically and must not show a
   separate pair-qualification panel.

## Office meal-pickup round trip

1. Start a new conversation and send:

   > 帮我取一下外卖。

2. While preparation is running, verify that the visible status changes between
   concrete stages and streams useful progress summaries. It must not expose a
   hidden model chain of thought, stay on an unexplained three-dot indicator, or
   fabricate completed work.
3. If more than one pickup point is plausible, verify that the assistant asks
   one natural Chinese question and offers A/B/C choices plus **其他**. Choosing
   **其他** must reveal an input field. Internal field names and error codes must
   not be shown. The application, not the user, supplies the default ten-second
   pickup hover, no-scan behavior, return trip and plan-before-execution flow.
4. Verify that the conversation title and plan are in Chinese. The plan card
   must contain the selected aircraft, map, route and ordered execution steps.
5. Click **开始仿真**. The application must acknowledge the command and keep
   **查看运行** disabled until a real live frame is available.
6. In **查看运行**, observe takeoff, corridor/door/stair transitions, outdoor
   safe-height changes, meal-point hover, payload transition, return flight and
   landing.

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
