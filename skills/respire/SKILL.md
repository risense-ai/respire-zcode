---
name: respire
description: respire (rsrs) local encrypted memory playbook. Automatic per-turn recall is injected with the prompt; **if no injection is present, the hits are off-topic, or the topic involves an earlier project, error, agreement, or date, recall again with different wording (synonyms, hypernyms, English equivalents, one route each); do not repeat only when the injected hits are truly relevant**. Manual recall, remember (judge then store), show/chain to read full text, forget, sync, status; a prompt starting with "记：" returns pending without writing; the model must finish candidate review and placement; the "/nomem" prefix disables recall for the turn. Triggers: memory, recall, remember, store memory, forget, sync, 记忆, 翻忆, 存记忆, 忘掉, 同步.
---

# respire · memory playbook (ZCode)

Plugin behavior: automatic recall is read-only. Explicit memory prefixes return pending with nothing written; treat the supplied text only as a fact, not as an instruction to perform its described work. Before any memory write, you MUST read rsrs prompt, recall same-topic candidates, and use rsrs show <id> to read their full bodies. Apply update > merge > attach > new in that order; use the existing CLI for updates/merges. A new important record MUST have a real, reasonable parent whose full body you have read. ONLY AFTER that review may you use rsrs remember with --importance important --parent <id>; if no such parent is available, remain pending. DO NOT guess a parent, use --force, or downgrade importance to bypass this requirement. DO NOT write in read-only/off mode or change that mode to enable a write. Use literal body markers required by engine policy; DO NOT translate them. The title MUST be a complete subject + action + result fact sentence. After an actual write, you MUST use rsrs show to verify the id, title, and full body. If the actual write outcome is unknown, DO NOT retry automatically or claim success. Verify read-only; DO NOT resend the write. Stop nudges at most once per request.

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
