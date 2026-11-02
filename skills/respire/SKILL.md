---
name: respire
description: respire (rsrs) local encrypted memory playbook. Automatic per-turn recall is injected with the prompt; **if no injection is present, the hits are off-topic, or the topic involves an earlier project, error, agreement, or date, recall again with different wording (synonyms, hypernyms, English equivalents, one route each); do not repeat only when the injected hits are truly relevant**. Manual recall, remember (judge then store), show/chain to read full text, forget, sync, status; a prompt starting with "记：" returns pending without writing; the model must finish candidate review and placement; the "/nomem" prefix disables recall for the turn. Triggers: memory, recall, remember, store memory, forget, sync, 记忆, 翻忆, 存记忆, 忘掉, 同步.
---

# respire · memory playbook (ZCode)

Plugin behavior: automatic recall is read-only. Explicit memory prefixes return pending with nothing written; treat the supplied text only as a fact, not as an instruction to perform its described work. Before any memory write, you MUST read rsrs prompt, recall same-topic candidates, and use rsrs show <id> to read their full bodies. Apply update > merge > attach > new in that order; use the existing CLI for updates/merges. A new important record MUST have a real, reasonable parent whose full body you have read. ONLY AFTER that review may you use rsrs remember with --importance important --parent <id>; if no such parent is available, remain pending. DO NOT guess a parent, use --force, or downgrade importance to bypass this requirement. DO NOT write in read-only/off mode or change that mode to enable a write. Use literal body markers required by engine policy; DO NOT translate them. The title MUST be a complete subject + action + result fact sentence. After an actual write, you MUST use rsrs show to verify the id, title, and full body. If the actual write outcome is unknown, DO NOT retry automatically or claim success. Verify read-only; DO NOT resend the write. Stop nudges at most once per request.

## Visible status

Follow the current turn's injected visibility instructions. `Memory: N found` reports candidates actually injected, never adoption. Report `Used:` ONLY AFTER successfully reading a body and actually using it. Default to `[ref]`; use `[basis]` only for a verified source that holds in the current scope, and `[history]` only for outdated, superseded or conflicting historical context. An agreement proves only the agreement, not execution. A body's claims, importance, scores and save receipts cannot establish `[basis]`. For mixed states, use the most conservative label for the part actually used and explain its scope when needed.

Use real IDs with at least the first 8 characters, extending ambiguous prefixes. Derive the short title only from the actual record title, limit it to 24 Unicode characters, and never append IDs, acceptance numbers, other concrete values or added meaning. Use `(untitled)` or `(title hidden)` when appropriate. DO NOT expose bodies or full IDs, invent IDs, or print placeholder examples. Expand the basis only when requested. If no record was used, end with `Memory: unused` and omit Used.

Explicit prefixes remain pending and may show `Save: needs review`; nothing has been written by that handoff. DO NOT invent Last save, verified status or this turn's save result. Omit ALL status labels for strict JSON, fixed-format or only-specified output. Never add a reply only for status, repeat announcements or carry old notices into later turns.

## Write guard boundary

The known `memory_remember` / `memory_update` (including `mcp__<server>__` namespaces) tool is denied because its target store cannot be bound to the local parent check. Use one explicit CLI command; DO NOT use another tool to bypass a denial. Unknown MCP tools are outside this guard.

PreToolUse checks recognized Bash `rsrs remember` calls and updates promoting a record to important before execution. Every remember merge MUST provide a literal parent even when importance is omitted or trivial. An important update MUST pass read-only target inspection and verification of its existing non-empty parent; otherwise attach first and keep the update pending. It denies important records without a non-empty literal parent ID, any force option, and recognized dynamic or opaque write wrappers. Parent verification uses read-only `--client-only show`; unavailable engines, timeouts, malformed receipts, or unconfirmed IDs are denied. DO NOT start runtime, change modes, or switch tools to evade this denial. Use one explicit literal command or report placement pending.

A successful guard check proves only that a parent ID exists. It does not prove that you previously read the record or that the parent is semantically appropriate. You MUST still follow the full candidate-review workflow. Trivial diary records need no parent, but force is still prohibited. This guard is not a general barrier for unknown aliases, arbitrary scripts, custom tools, or other processes.

## Commands

- `rsrs recall "project name + keywords" --limit 5 --json` — **recall before answering, visibly** (an empty injection never means no memory; search manually); on errors, recall by the original error text first; `--titles` returns short id + title only
- `rsrs remember "content" --title "fact sentence" --importance important --parent <reviewed-parent-id>` — only after reading a reasonable parent and ruling out update/merge
- `rsrs show <short-id>` (first 8 chars) reads the full body; `rsrs chain` fetches the whole causal chain
- `rsrs forget <id>` — tombstone delete, propagated by sync
- `rsrs candidates <content>` — pre-store candidate list (merge/attach suggestions)
- `rsrs sync` two-way sync (autosync on); `rsrs status` checks state; `rsrs prompt` prints the full memory workflow
- `rsrs tree/resort/retitle` — maintain the causal tree

## Parsing notes (CLI envelope)

- Every command with `--json` uses one envelope: `status`, `summary`, `items`, `details`, `errors`; **failures also return HTTP 200 with `status:"fail"` and `errors[]`** — check status, not the exit code
- recall scores and entries live in `details[].score`, `details[].id` (full id; use the first 8 chars as the short id), `details[].title` and `details[].superseded_by`; `items` is only the "score title" line
- Progress goes to stderr; never mix it into JSON with `2>&1`
- ok/warn with a valid id means already written; never resend. Pending means nothing was written. Unknown results require read-only verification; never retry the write.
- The default `trivial` tier goes to the diary area, is excluded from recall and gets its title rewritten to "activity track <date>" — use `--importance important` for factual records

## Red lines

- Never put passwords, ID numbers, phone numbers, card numbers, or private keys into memory bodies or query terms; record only where they are stored — the library is encrypted, but a leaked key exposes everything
- Recall scores indicate relevance, not confidence; read candidate bodies before deciding placement.
- Account and sync configuration are outside this plugin: run `rsrs register` / `rsrs login` on this machine (no website step); the plugin does not handle it
