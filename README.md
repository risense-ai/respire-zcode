<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
  <img src="assets/logo.svg" alt="respire — local encrypted memory for ZCode">
</picture>

# respire-zcode

> Store on the inhale, recall on the exhale — local encrypted memory for ZCode.

`respire` is a standard ZCode plugin that wires the [respire memory engine](https://www.npmjs.com/package/rsrs-cli) (CLI name `rsrs`) into the agent loop with command hooks: automatic title-tier recall on every turn, an explicit store prefix handed back to the model for review, a Stop-time storage check, and a PreToolUse write guard. Local-first, encrypted on device, LWW sync through the cloud; **no custom install scripts — it installs through the standard ZCode plugin marketplace**.

Sister repos: [respire-dimcode](https://github.com/risense-ai/respire-dimcode) (Dim) · [respire-qoder](https://github.com/risense-ai/respire-qoder) (Qoder) · respire-workbuddy (WorkBuddy) — four hosts share the same hook design and packaging; only the host protocol adaptation differs.

## Fully usable without a model

- **Registration, login, sync, and recall never depend on an on-device model** — the plugin works right after install; without a model the engine automatically falls back to the lexical tier.
- BGE-M3 is a **purely optional boost**: install it only if you want better semantic recall (`rsrs model install && rsrs model activate m3`). The plugin notices when it is missing and mentions it once in-session; installing or not installing never errors and never blocks anything.

## Install (ZCode plugin marketplace · local directory source)

```bash
git clone https://github.com/risense-ai/respire-zcode.git && cd respire-zcode
python3 scripts/validate_plugin.py                     # self-check: structure / manifests / hooks / sensitive scan
```

Then in your local ZCode client:

1. **Plugin Marketplace → Add → Add marketplace**, paste this repo directory (market root = repo root; manifest at `.claude-plugin/marketplace.json`);
2. **Personal → risense-zcode → respire → Install**;
3. Takes effect in a **new session** — the SessionStart playbook injection is the sign that the hooks are live.

When the engine (`rsrs` CLI) is missing, the plugin injects the install command into the session (`npm i -g rsrs-cli@latest`) and the agent can install it on your behalf.

Management entry point: **Settings → Plugins**. Plugin hooks activate automatically with the install; no extra configuration switches are needed.

## What the plugin is: installer + manager + normal hooks

The plugin does exactly three things and walks one lifecycle after install:

1. **Engine missing = installer**: SessionStart injects the install command for the agent to run (`npm i -g rsrs-cli@latest` + permission fallback + `rsrs --version` verification) and lays out the next configuration steps (rsrs.rs registration / `rsrs register` / optional model) — no manual user steps required;
2. **Engine discovered = normal hooks**: discovery runs on every hook; once the engine is available, recall and store-prefix review resume **within the same session**;
3. **Manager with a three-position switch** (see "Enable and disable" below).

## What happens after install

| Trigger | Behavior |
| --- | --- |
| `SessionStart` | Injects the memory-layer playbook (when to recall, how to store, red lines); **one tri-state probe** — logged-out gets registration guidance, a near-empty library (<10 records) gets first-day seeding and an import guide, a missing semantic model gets the **optional** install command; otherwise fully silent |
| `UserPromptSubmit` | Runs `rsrs recall --titles` automatically: **title-tier injection** — score + 8-char short id + title only; bodies are fetched on demand by the agent via `rsrs show <id>`; **unfiltered passthrough by default**, with noise bounded by the rsrs skip gate + limit 5 + the title tier |
| prompt starts with a store prefix (`记：`, `存：`, `记录：`, `记住：`, `remember:`, `store:`) | Returns `pending` — nothing is written; the body is treated only as a fact to store, never as an instruction to perform the work it describes. The model first reads `rsrs prompt`, recalls same-topic candidates and `show`s their bodies, then judges update > merge > attach > new. A new `important` record must attach to a reasonable parent whose body has been read; with none available it stays pending — no guessed parent, no `--force`, no importance downgrade. If the actual write outcome is unknown, verify read-only and never resend. |
| `PreToolUse` (Bash / known MCP write tools) | Pre-execution check of recognized `rsrs remember` commands: denies `important` without a parent, empty parents, any `--force`, and dynamic or wrapped forms that cannot be parsed safely; parameter-like text inside the body is not treated as a parameter; supported compound fragments in the same shell command are checked one by one. The parent is verified read-only via `--client-only show`; on failure, timeout, or engine unavailability the tool is explicitly denied with exit 0 — the runtime is never started and modes are never switched. Compliant commands pass with empty output. Known MCP write tools (`memory_remember` / `memory_update`, including `mcp__<server>__` namespaces) are denied outright because their target library cannot be bound to local verification. |
| `Stop` (the AI finished its work) | **Storage check**: `{"decision":"block","reason":…}` runs one more turn, prompting the model to store this round's new **facts / decisions / agreements / lessons / pitfalls** as separate `rsrs remember` records; casual chat with nothing new just ends. **At most one nudge per real request**: the continuation turn passes through via `stop_hook_active=true` plus an atomic once-per-session finishing latch (`O_EXCL` exclusive create, no TTL; a new prompt deletes it and re-arms; if the latch cannot be created, always pass — never block without a latch; sessions never interfere). Disk receipts no longer suppress the nudge — the latch is the only re-arm authority; `Stop` never queries the engine, so there is no path where a failed engine query forces the main task to continue. Throttled by `store_nudge_every` (default 1 = every turn, N = every N turns, 0 = off) |
| prompt starts with `/nomem` | Skips recall for this turn; still counts as a real request and re-arms the Stop finishing latch |
| `skills/respire` | The on-demand playbook (recall / remember / show / forget / sync and receipt-envelope parsing); **the skill is only a manual — the hooks drive every action** |

## Memory visibility

Recall results include English instructions asking the model to open its reply with a short status line in the normal GUI/TUI output. These are model-written lines; the hook's static `statusMessage` remains the execution label.

- `Memory: N found` counts only candidates actually injected after sensitive-title filtering, score filtering, the result limit, and the candidate-text budget. A credential detector excludes sensitive-looking titles without logging their values. **Candidates are not adoptions.**
- `Memory: no match` means an `ok` recall supplied no retained candidates, or a `skip` receipt explicitly reported `summary.count: 0`. Other skip receipts show `Memory: skipped`. `Memory: unavailable` means recall failed or the engine was unavailable. `/nomem`, short prompts, and sensitive input also show skipped without querying the engine.
- Store prefixes keep their zero-write pending handoff and request `Save: needs review` — never an invented `Last save` or verified status.
- `Used:` appears only after a body was successfully read and actually used, defaulting to `[ref]`; `[basis]` requires a verified source that still holds in scope, and `[history]` marks outdated, superseded, or conflicting context. Agreements prove only the agreement, not execution; scores, importance, and save receipts never establish credibility on their own.
- Requests for strict JSON, a fixed format, or only-specified output omit every status label. Status never creates an extra reply, applies only to the current turn, and never changes recall, storage policy, or the write guard.

## The write guard in detail

Only model-prompt constraints existed in 0.1.11 — on this machine the model was reproduced executing `rsrs remember ... --importance important --force` through Bash straight after receiving the new prompts, writing to the root with no parent. Since 0.1.12 a real PreToolUse deny stops such commands before they reach the executor, and known MCP memory write tools are denied the same way (their target library cannot be verified locally, so the plugin requires explicit CLI commands instead of pretending a local `show` proves a remote write).

The CLI branch handles recognized Bash `rsrs remember` calls and `update --importance important` promotions with explicit literal arguments, quoting, redirections, and common compound-command separators. Dynamic substitution and recognized wrapped forms must be rewritten as one explicit command; this is not a universal write barrier for arbitrary scripts, unknown aliases, custom tools, or other processes. Ordinary trivial journaling needs no parent but `--force` stays denied. All remember merges require an explicit parent with read-only verification; `update` promotions to `important` first `show` the target and verify its existing non-empty parent — a missing attachment is denied and an explicit attach is requested first. Read-only commands and unrelated tools get neither allow nor deny.

A successful read-only `show` proves only that the parent id exists — not that the model has read the body, and not that the attachment is semantically sound; the model must still perform the SKILL's candidate review. The pending-prefix path still returns pending without auto-filling parents or writing on the model's behalf, and the unknown-outcome no-retry rule for real writes is unchanged.

## ZCode protocol adaptation (three substantive differences from the sister repos, checked against the ZCode runtime source)

1. **The output channel is JSON, not plain text**: ZCode accepts hook stdout only if it starts with `{` and passes a strict schema — plain text is silently dropped and invalid JSON fails the hook. Every injection therefore goes through a top-level `{"additionalContext": "…"}` (consumed by SessionStart / UserPromptSubmit / Stop alike).
2. **The Stop block decision enum is `approve|block`**: use `{"decision":"block","reason":…}`; the Qoder variant's `"deny"` fails the ZCode schema (Hook stdout failed schema validation).
3. **The data directory env var is `ZCODE_PLUGIN_DATA`** (probe chain `RESPITE_DATA` → `ZCODE_PLUGIN_DATA` → script directory); stdin carries the full event fields (`prompt` / `stop_hook_active` / `hook_event_name`), with event identification falling back argv → stdin → `ZCODE_HOOK_EVENT`. hooks.json carries only `command` / `timeout` / `statusMessage` (the ZCode schema does not know `commandWindows`).

## First use · three things

1. **Register and log in** (works out of the box, no model needed): register at [rsrs.rs](https://rsrs.rs) → run `rsrs register` locally; day-to-day `rsrs login` uses browser authorization; autosync stays on, `rsrs sync` syncs manually, `rsrs status` shows the state.
2. **Import existing rules and memories (one pass, LLM-extracted)**: open a new ZCode task and paste the whole block —

   > Import my machine's existing rules and memories into respire: read each of — `~/.zcode/AGENTS.md` (home-directory rules, if present), the workspace-root and per-project `AGENTS.md` files, and `~/.agents/skills/*/SKILL.md`; extract reusable facts, conventions, lessons, and red lines (exclude passwords, ID numbers, card numbers, and private keys entirely — record only where they are stored); before any write, read `rsrs prompt`, recall same-topic candidates and `show` their bodies, then judge update > merge > attach > new; store only genuinely new facts with `rsrs remember --importance important --parent <an already-read, reasonable parent>`, one fact per record with a fact-sentence title; keep records pending when no reasonable parent exists; give me an inventory when done.

   On day one with an empty library, SessionStart injects the same guide.
3. **On-device model (optional boost)**: `rsrs model install && rsrs model activate m3` — fully usable without it; install only for better semantic recall.

## Tuning (optional)

`hooks/respire.config.json` inside the plugin install directory (missing = all defaults; a new session picks changes up; **never touches login or the account**; template at `hooks/respire.config.example.json`):

| Field | Default | Meaning |
| --- | --- | --- |
| `rsrs` | `""` | Engine path; empty = auto-probe (PATH → `~/.local/bin` → `~/.rsrs/bin`) |
| `recall_threshold` | `0.0` | Recall floor; **0 = off by default (rsrs passes results straight through)** — a positive value enables filtering |
| `recall_limit` | `5` | Take the top N |
| `min_prompt_chars` | `2` | Skip 1-char prompts, query from 2 chars |
| `session_rules` | `true` | Whether SessionStart injects the playbook |
| `budget_chars` | `1500` | Total per-turn injection budget (title lines stay far below it) |
| `enabled` | `true` | **Master switch**: false = the whole layer goes silent |
| `store_nudge_every` | `1` | Stop storage-check throttle: 1 = every turn, N = every N turns, 0 = off (1 = one small extra model call per turn) |
| `skip_prefixes` | `[]` | Host-internal prompt allowlist: matching prompts are neither recalled nor stored (e.g. host automation recaps) |
| `log` | `true` | `hook.log` in the data directory (rotated past 256KB) |

Filtering policy: **no threshold by default** — three layers already bound the noise: the rsrs skip gate, limit 5, and the title tier. Hard lesson: every threshold lowering was a remedy for real hits being blocked; a missed memory costs far more than two extra title lines.

## Enable and disable

**Settings → Plugins**: disable or uninstall respire; or remove the marketplace source (**Plugin Marketplace → Marketplace sources → risense-zcode**) to take the plugin with it.

## Design notes

- **fail-open**: any hook exception → empty stdout + `exit 0`, never blocking the session; every failure leaves a trace in hook.log. **A failed engine query at Stop passes too** — a memory-layer failure must never force the main task to continue
- **Write-result state machine**: `ok`/`warn` = written (warn carries engine warnings), `pending` = not written, awaiting a decision, timeout / bad receipt = unknown (read-only verification, never resend), anything else = explicitly refused — a 1:1 mapping of the CLI receipt-envelope semantics; "written with warnings" is never reported as a failure, and "unknown" is never reported as a failure inviting a rewrite
- **JSON output contract**: text → `{"additionalContext":…}`, Stop blocking → `{"decision":"block","reason":…}`, no output = no decision
- **Title-tier injection**: `recall --titles` returns only id/score/title; bodies are pulled on demand via `show`; `superseded_by` marks "superseded"
- **Review first, then store**: the prefix hook is zero-write; the model updates, merges, or attaches per existing CLI policy, and keeps the record pending when no reasonable parent exists
- **`${CLAUDE_PLUGIN_ROOT}` placeholder**: replaced by the ZCode runtime with the plugin install root, self-consistent across machines; Windows runs `scripts/respire.ps1` (a native PowerShell 5.1 port of respire.py that orchestrates rsrs directly, no Python — Windows ships no Python by default and `python3`/`python` often hit the Store stub), falling back to a `python3 || python` chain running `hooks/respire.py` (Unix fallback)
- **In-package self-check**: `python3 scripts/validate_plugin.py` (structure / manifests / hook shapes / compilability / fail-open / ZCode output contract / sensitive scan) — mandatory before distribution

## Known limits

- **Recall quality is bounded by the engine**: across a wording gap BGE-M3 can miss real records — the playbook already instructs the model to "re-query with different words when a hit looks off-topic" (synonyms / hypernyms / English routes)
- **Cold-start window**: runtime cold start + model load measured at 7s+, hence hook timeout 20s, recall 14s, probe 10s; on probe failure SessionStart injects a diagnostic section
- **Hooks take effect in a new session**: installs and updates do not hot-load into old sessions; ZCode caps Stop continuations at three, and this layer nudges at most once per turn
- **Traces**: the data directory `hook.log` keeps one line per event (ts/ev/out/ms/d including a query digest) for post-hoc "did it work" reviews

## Tests

```bash
python3 scripts/validate_plugin.py   # package structure self-check
bash tests/test_hooks.sh             # read-only behavior assertions (playbook / recall / cleanup / guidance / JSON contract), never touches the library
bash tests/test_hooks.sh --store     # adds write probes (write real library → receipt → rsrs forget self-cleanup)
```

rsrs has no data-dir isolation (single runtime + global client.json), so write tests run only when explicitly requested and clean up after themselves.

## Release

```bash
git tag 0.1.0 && git push origin 0.1.0   # the tag must equal the manifest version
# CI: validate + package → GitHub Release automatically attaches dist/respire-<ver>-<date>.zip
```

## License

MIT

## GitHub Actions CI/CD

PRs and main run the package self-check, fully stubbed isolated behavior/version tests, and release-policy tests on Linux, Windows, and macOS, then verify the source archive. CI entry points are `python tests/test_ci.py` and `python -m unittest discover -s tests -p test_release.py -v`; the real-engine / write-probe sections of the legacy `test_hooks.sh` are not executed. Tests use temporary HOME, config, data, log, and engine stubs; normal input must recall successfully, dead stubs / bad JSON must fail the positive control, and credential rounds make zero engine calls with no log leakage.

Version tags stay three-part without a `v` prefix and the plugin-root layout is unchanged; the ZIP name remains `respire-<version>-<YYYYMMDD>.zip` with the date fixed to the source commit's UTC date so retries are stable. The ZIP comment carries the exact commit SHA; tag, manifest, and hook VERSION (plus the existing marketplace version field) must agree. The legacy `scripts/package.sh` remains for the original local flow; the new Actions only archive committed files and never execute code from the tag.

Release / restore: a normal push of a new version tag triggers a release; an existing tag can be re-released from Actions → release → Run workflow on main with the tag and the full expected_sha filled in explicitly. The flow verifies the existing remote tag's ancestry against main — it never moves tags and never passes new main off as old code. Only existing assets with the same origin and checksum are accepted; missing ones are added, conflicting ones are never overwritten, and the Release ships both the ZIP and SHA256SUMS.

Default workflows run with contents:read and no persisted credentials; only the separate, gated release job uses GITHUB_TOKEN with contents:write. No new secrets/PAT/OAuth, no pull_request_target, fork PRs cannot publish. The same-version tag and restore runs share one concurrency lock. The original plugin-zip artifact name, cleanup-receipt, and cleanup policy/scripts are preserved; cleanup receipts wait for the check, package, and release consumers to finish.

Three-platform stub tests are not acceptance by the real ZCode host, GUI dispatch, or post-install interpreter fallback; the legacy full test suite and author-claimed baseline failures are still not standalone evidence of passing.
