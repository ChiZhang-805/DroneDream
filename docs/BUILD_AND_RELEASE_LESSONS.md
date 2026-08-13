# Build and release lessons

This is the single maintained record for repeatable build and deployment lessons. Add a concise root cause, cleanup outcome, and verified fix; do not create parallel incident-note files.

## 2026-08-13 — Settings console and allowance cards

- Success: verify the 860×500 settings surface at the 1337×800 and 1440×900 browser sizes in all six interface locales. The automated check must reject internal scrolling and clipped leaf text; final screenshots still require visual review.
- Failed local site build: the Pages config requires `VITE_SUPABASE_PUBLISHABLE_KEY`, not the older anonymous-key variable name. Vite stopped before writing a new release; the next successful build emptied and regenerated `frontend/site-dist`.
- Failed database migration: a joined CTE used unqualified `created_at`, which exists on both tables. PostgreSQL rolled the migration back transactionally, so no partial card set remained. Qualify joined columns (`cards.created_at`, `cards.card_id`) and include an end-of-migration assertion for the exact expected card inventory.
- Failed regression command: npm was first invoked from the repository root, but this workspace keeps `package.json` under `frontend`. Remove the generated npm debug log and run all frontend checks from `frontend`.
- Failed preference regression: changing the interface language retriggered the initial preference-loading effect because presentation state was an effect dependency. Snapshot the initial fallback presentation values in a ref so locale and appearance changes save preferences without reloading them.
- Cleanup: generated `frontend/site-dist`, Playwright screenshots, and `supabase/.temp` are local artifacts and must remain ignored or be removed after verification. Secrets never belong in build logs, screenshots, commits, or this document.
