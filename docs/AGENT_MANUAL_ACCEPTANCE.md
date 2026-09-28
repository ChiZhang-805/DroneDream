# DroneDream · AGENT manual acceptance

This checklist starts after the signed Windows installer has been installed. It
tests the user-visible workflow without requiring a developer terminal or
deleting existing conversations.

## Before the mission

1. Open **DroneDream · AGENT** and sign in. The window title must contain only
   the product name.
2. Open **Maps**. A bundled map must show its pre-parsed status. Importing or
   updating a user map must create a content identity; an unchanged map must
   reuse its existing analysis, while a changed map must invalidate only the
   affected map/aircraft qualification.
3. Open **Aircraft**. The default resource catalog must list the reviewed PX4
   aircraft. Selecting a resource must show its sensors, nested model
   dependencies, recommended tasks, excluded tasks, pinned source revision,
   license, and readiness. Preparing an on-demand model must add the resulting
   asset version to the account library without restarting the application.
4. Select one aircraft/map pair that is marked qualified. A catalog entry that
   still needs dependencies or pair qualification must not be presented as
   flight ready.

## Office meal-pickup round trip

1. Start a new conversation and send:

   > 从办公室出发，帮我去取餐点拿一下外卖，再带回办公室。取餐时悬停10秒，不用扫码。先给我计划，等我确认后再开始。

2. While preparation is running, verify that the visible status changes between
   concrete stages and streams useful progress summaries. It must not expose a
   hidden model chain of thought, stay on an unexplained three-dot indicator, or
   fabricate completed work.
3. Verify that the conversation title and plan are in Chinese. The plan card
   must contain the selected aircraft, map, route and ordered execution steps.
4. Click **开始仿真**. The application must acknowledge the command and keep
   **查看运行** disabled until a real live frame is available.
5. In **查看运行**, observe takeoff, corridor/door/stair transitions, outdoor
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
