# DroneDream public website design guide

The public website treats copy layout as part of the visual system, not as an afterthought.

## Bilingual copy rhythm

- Any explanatory block that renders on two or more lines should finish with a visually complete final line. At the canonical review viewports, the final line should occupy at least about 80% of the available text measure.
- English and Simplified Chinese are authored independently for visual parity. Preserve the same meaning and hierarchy, but prefer matching line counts and similar final-line fill over literal translation.
- Revise wording before changing font size or forcing justification. Do not stretch the final line with `text-align-last: justify`.
- Validate both locales at 1440 × 1000 and 2048 × 1280 desktop viewports. Mobile screenshots remain mandatory, but natural wrapping takes priority over an exact 80% threshold on very narrow screens.

Run the automated desktop audit against a local preview:

```powershell
node website/scripts/audit-site-typography.mjs http://127.0.0.1:4174 1440 1000 0.80
node website/scripts/audit-site-typography.mjs http://127.0.0.1:4174 2048 1280 0.80
node website/scripts/audit-site-typography.mjs http://127.0.0.1:4174 390 844 0.80 mobile-layout.json layout-only
```

## Clickable affordances

- Primary navigation may use text-only links because its location and behavior are conventional.
- Other links use an icon or an icon plus text. A pure text phrase must not be the only visual affordance for navigation or download.
- Decorative icons are hidden from assistive technology; the visible label or the link's accessible name must still describe the action.

## Release review

- Build and lint before deployment.
- Capture every major section in both locales at desktop and mobile sizes.
- Inspect the manual dialog, capability card front/back states, workflow motion, download metadata, keyboard focus, reduced-motion behavior, and the public release manifest.
- Deploy atomically, then repeat the smoke test and visual capture against the public origin.
