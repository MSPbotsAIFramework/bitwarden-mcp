# PRD-22483 · Code review

## Round 1 · 2026-11-26 · reviewed dev/PRD-22483 b40e38f (base fee1516)

Verdict: changes requested

### Findings
1. [must-fix] src/bitwarden_mcp/send_crypto.py:22,119 — The default-region (US cloud) share link is built as `https://send.bitwarden.com/#/<accessId>/<seed>` (the base ends in `#` and `send_link` then adds `/`). The live redirect script at `https://send.bitwarden.com/script.js` does `hash.slice(1).split('/')` and only redirects to the vault when the result has exactly 2 parts; `#/<id>/<key>` gives 3 parts (`['', id, key]`), so no redirect happens and the link never opens the Send. Bitwarden clients build the default link as `https://send.bitwarden.com/#<accessId>/<key>` (no slash after `#`); only the vault-host form uses `/#/send/<accessId>/<key>`. This breaks AC1/AC2 (link must open the secret) for every US-cloud tenant. Fix: make the default-region link `https://send.bitwarden.com/#<accessId>/<fragment>`, keep the `<vault>/#/send/<accessId>/<fragment>` form for EU and self-hosted, and update `tests/test_send_crypto.py:61-70`, the design doc link example and the TC-BWS-004 / manual-case expectation (`PRD-22483.ac.json:185`) accordingly. Evidence: `curl -sL https://send.bitwarden.com/script.js` output quoted above.
2. [suggestion] README.md (tool table and header table) — the new `bitwarden_create_text_send` row and the three new header rows are separated from their tables by a blank line, so they render as stray text rather than table rows. Remove the blank lines.

### Fixes
