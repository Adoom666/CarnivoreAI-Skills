---
name: huddle
description: How every Claude session in a Carnivore project uses the huddle (the owner's "interactive todo") through the carnivore MCP tools huddle_*. Use when a tell says "the interactive todo list ... changed", when you see or add a huddle item, or when you need to ask, report, review or hand work to the owner through the huddle.
---

# huddle: the interactive todo

The huddle is the owner's shared todo list. The owner reviews it by color and icon, not by reading the terminal. Use the carnivore MCP tools `huddle_*` (load them with ToolSearch if deferred). Every rule below is the standing way to work.

## 1. Reading
- A tell that says "the interactive todo list ... changed" carries a list id and a since-cursor.
- Read it with `huddle_changes` using those two values. Answer in the huddle, not in the terminal.

## 2. Titles
- Every item has a short descriptive `title` (max 120 characters).
- If an owner-written item has no title, write one as soon as you see it.

## 3. Groups (every item is in one)
- EVERY item belongs to a group (the `group` field). No item is ever left ungrouped, including the ones you create: pass `group` on `huddle_add`, or `huddle_move` it right after.
- When you read a list, move any ungrouped item into the group that fits.
- If the owner put an item in the wrong group, or in none, move it with `huddle_move`.
- If no group fits, create one (`huddle_group_create`).
- Never make a group named after a status (no "Done", "Blocked", "In progress").

## 4. Guide revision
- The huddle tools may report a guide revision (`guide_rev`) in their answers or in a tell. When it differs from the one you last saw, re-read this skill before your next huddle write: the rules below may have changed.
- If nothing reports a revision, there is nothing to compare; carry on.

## 5. Reply kinds
- **info:** an fyi while you work. Use `huddle_reply`. The owner sees each unread info in full on the row and marks each read on its own. An info never changes the item's status or section, and never ends working.
- **attention ("look"):** you want the owner to check something. A look is just like an info on the row: the owner sees each unread look in full, in the attention color with its own look icon, and marks each read on its own. A look never changes the item's section, but it ends working (you are presenting). It still marks the item unread and badges the huddle tab.
- **answer:** you are replying to a question the owner asked (in the huddle thread, or outside it). Use `huddle_reply` with `kind: answer` and QUOTE the owner's question: `quote` is the id of the owner's message on that item (the server snapshots its text), or `quote_text` is the owner's words when they asked outside the huddle. The row shows ONE box, the owner's question muted on top and your answer below in markdown. It behaves like an info (not unread, no badge, never changes the status). Use `answer` when replying to the owner's question, `info` for an fyi they did not ask for. Form answers from the owner carry an `_extra` {text} entry in `answers` when the owner wrote something in the anything-else box: read it.
- **question:** you are blocked. Use `huddle_ask`, never `huddle_reply`. Ask it STRUCTURED: put any explanation in `context` (background, shown apart in a muted block) and the asks in `questions`, a list of short, precise questions (one per entry, no explanation inside) that the owner sees numbered and answers by number ("1 yes, 2 the second"). Use `text` only for a single plain question. The batch `ask` op takes the same fields.
- Keep every question short. When it needs explaining, post the explanation first as an info (or an answer, when replying to the owner's question), then ask the short question; prefer a typed form (section 14) over free text.
- Never put a question in an info.
- **Lead, then details:** start every info and look with a ONE-LINE LEAD (a short plain sentence, under about 100 characters), then a line break, then the details. The owner's row folds a long note (past about 240 characters or 3 lines) to that lead, with a chevron that opens the rest. Keep notes short; a note under about 240 characters shows whole.

## 6. Working
- Set `state` to working with `huddle_update` when you START. It is durable: it stays working across idle, restarts and dead sessions.
- It ends only when you post a question (`huddle_ask`), post a look, set `done_by_claude`, `waiting_install` or `open`, move it to `back_burner`, or the owner ticks or deletes it. An info does not end it, and neither does the owner's reply.
- A tell you picked up is working too, until one of those.
- Because it is durable, set `open` or `done_by_claude` yourself when you stop an item.
- A `back_burner` item is wanted but not today: do not work on it unless the owner asks; set `state` `back_burner` only when the owner asks, and `open` takes it off.
- An item you only read stays open.
- When the owner asks what's next or what's open, list working items first and resume them, then the open ones.

## 7. Review
- When the work is committed but not yet installed in the app the owner will review it in, set `state` to `waiting_install` (its own "waiting to install" section); after the install, set `done_by_claude` for review.
- When finished, set `state` to `done_by_claude`.
- Fill these in the same update. They show in the review block without opening the row. A review stays in the review section in the blue review color, never in "needs you", and its row shows no action tag:
  - `review_action`: what the owner must do. `tick` (check and tick), `push` (check and tick to push), `answer`, `read` (read only), `none` (no action needed). Unset reads as `tick`. Always set it.
  - `review_description`: what changed and what to check. It renders markdown (lists, bold, code, tables), so write it for easy reading.
  - `review_link`: a clickable link, only when one helps (an in-app path or an https URL).
  - `review_where`: a short LOCATION to look ("Settings, Huddle tab"), only when useful. It is NOT a click path: no step-by-step menu trail, no version numbers, no "reload".

## 8. Answers given outside the huddle
- When the owner answers in chat or in the terminal, call `huddle_mark_answered`.
- Also post an info reply recording the owner's decision, so the row's last line is not a stale question.

## 9. Surfacing
- To get the owner's eyes on something, post a look reply (it shows on the row in full, and badges the tab) and call `huddle_focus`.
- A look moves into the "needs you" section only when it carries an `action` (`tick`, `push`, `answer`, `read`); a look with no action, or `none`, is an fyi that stays put. An item in review never moves to "needs you", look or not.
- In normal density, pass `open: null`. The row shows the reply box, so it does not need opening.
- The owner reviews by color and icon in the huddle, not in the terminal.

## 10. Approval
- A tick (approved) is the owner's alone. Never tick for the owner.
- `review_action: push` asks the owner to check the work and tick to approve a push. Never push on your own; follow the project's own rules for what a tick authorizes.

## 11. Batching and lean answers
- Two or more edits (adds, state changes, replies, moves) in one go: send ONE `huddle_batch` call (`list_id`, `ops`, at most 50), not one tool call each. An `add` op takes the `huddle_add` fields (no item_id) and its own optional `list` (default `list_id`), so one call files items across projects. It answers per op `{item_id, ok, state, revision}` and is not atomic: read the `ok` flags, the earlier ops stay applied.
- Single writes (`huddle_add`, `huddle_update`, `huddle_reply`, `huddle_ask`, `huddle_move`, `huddle_mark_answered`) answer lean BY DEFAULT: `{item_id, ok, state, revision}` (plus `message_id`). Pass `lean: false` only when you need the full item and its thread back.
- `huddle_list` is a LEAN read by default: one summary row per open item (`id`, `number`, `title` (or the first 120 characters of the text), `status`, `section`, `unread`, plus `group`, `needs_action`, `forked_from`, `review_action` when set), no threads, no approved items (the answer says `approved_hidden`). Opt in with `fields` (a list of `text`, `note`, `thread`, `review`, `state`, `kind`, `revision`, ..., or `full` for the whole item), `include_approved: true`, `item: <id>` (ONE item in full with its thread: use it before you edit or reply on an item whose text you need), `limit` (default 100) and `cursor` (the previous answer's `next_cursor`; it is a paging offset, not the change cursor). Reading the list still counts as reading the approved items it hides.
- `huddle_changes` is lean too: groups come only when they changed since your cursor (or on a reset); an item whose revision and group you already hold (from a list read of any shape, or an earlier changes) arrives as `{id, status, section, revision}` whatever moved it (a new message, a bulk renumber); read an item's text with `huddle_list item`. Your OWN posts are left out of `messages` (`omitted_own` counts them; `include_mine: true` keeps them); the owner's posts always come whole. A form question or answer message sends its `form` / `answers` structure plus only a one-line `text` lead.
- `huddle_focus` with `list: "all"` accepts items from any project's list.

- `huddle_delete` (or a `delete` op in `huddle_batch`) is a soft delete of any item. Use it only when the owner asks, or for your own throwaway test items; never to tidy his list.

## 12. Names
- The owner reads titles. When you mention an item in a reply, review field or chat message, name it by its title in quotes. Ids are for tool calls only.

## 13. Formatting and data
Your posts (huddle_reply, the context of huddle_ask) render a safe markdown subset: **bold**, *italic*, `code`, fenced code, `-` and `1.` lists (one nested level), `#` and `##` headings (drawn small), `[text](https://...)` links (http and https only), pipe tables and a key: value block. HTML shows as literal text. Use the form that fits: a pipe table to compare things or list rows of data (numeric columns right-align on their own), a ```kv fence of `key: value` lines for a few labeled facts (branch, status, count), a short list for steps or options, prose otherwise. Keep the one-line lead first, then the details. An item's own text (huddle_add, huddle_update) stays plain.

## 14. Tool reference (moved out of the tool descriptions, which stay under 400 characters)
- **Statuses and sections** (an item's `status` and `section`; its `state` decides the section, an info or look never moves it): `question` (your question waits on the owner), `review` (you marked it done), `waiting_install`, `working`, `waiting_to_send` (the owner changed it and neither a tell nor your read has carried it yet; only a read by the list's own session, the session its tell went to or is held for ends it), `scheduled`, `open`, `back_burner`, `done` (approved). Numbers are the owner's view order; a checked item's number is null.
- **Working is durable** (see section 6): a read alone never makes an item working; a tell you picked up does.
- **Groups are areas** (widgets, mcp tools), never states. Each list answers its named groups (`id`, `name`, `position`); an item's `group` is null when ungrouped.
- **Messages**: each thread message has a `kind`: `question`, `attention`, `info` (yours), `reply` (the owner's). An unread info the owner has not read carries `unread: true` and the item `info_unread`. A message the owner attached files to carries `files: [{name, mime, size, path}]`; every `path` is ABSOLUTE and local, so Read it (an image or a document) to see what the owner sent.
- **Typed questions** (`huddle_ask` `questions` entries as objects `{id, type, prompt, required?, help?}`): `yes_no` (`labels` [yes, no]?, `recommend` {value, reason}?), `single` or `multi` (`options` [{id, label, recommended?, reason?}], `other: true` adds a free-text box, multi takes `min` / `max`), `rank` (`options`, `recommend` {order: [every option id], reason}?), `short_text` or `long_text` (`placeholder?`, `max_length?`, `recommend` {text, reason}?). Name ids (`i54`, `fold`): the answer comes back keyed by them. Mark a recommendation with a reason whenever you have one. A form is answered ONLY by the owner's submit: the owner's plain reply on it is a comment. The answer arrives as their next message with `answers_to` (the question's message id) and `answers` {question id: {value | choice | choices | order | text, prompt, recommended?, note?, skipped?}}.
- **Scheduling** (`huddle_add` / `huddle_update`): `fire_at` (ISO 8601 WITH a UTC offset, in the future; empty cancels) tells the item's session when it comes due, waking or starting the project's session first; approving or deleting the item cancels it and a back_burner item does not fire. An open item with a pending `fire_at` has status `scheduled` until it fires; a failed fire shows its error and leaves it open. `repeat` ({freq: daily, time: 'HH:MM'}, {freq: weekly, byweekday: [0-6, Monday is 0], time}, {freq: hourly, interval: N}, {freq: monthly, monthday: 1-31, time}; times are 24-hour in the app's configured time zone and DST-safe; empty string stops) re-arms after each fire; a missed occurrence while the app was down fires once. `paused` pauses or resumes a repeat; `fire_now: true` runs the item now through the same delivery (refused for an approved or back_burner item). `start_trigger` on an item shows all of it.
- **Forking**: `huddle_fork` makes a new item beside one (title and text copied unless given); `fork_state` sets the fork, `parent_state` the original, in one transaction (never an approved state); the fork records `forked_from`.
- **Moving**: `huddle_move` sends an item to the bottom of another list (project ids from `projects_list`; `all` is the shared list) and/or into a group (an id or area name; a new name makes it; null ungroups). Numbering recomputes in both lists.
- **Deleting**: `expected_revision` on `huddle_delete` / `huddle_update` refuses the write if the item changed since you read it.
- **Plain text vs markdown**: an item's own `text` is plain; formatted detail goes in a `huddle_reply` post. `huddle_batch` ops take that op's own tool fields (`add`, `update`, `reply`, `ask`, `move`, `mark_answered`, `delete`, `fork`); `list_id` is the list every item must be in (`all`, a project id, or `mine`); at most 50 ops; `stop_on_error: true` skips the rest after the first failure.

## 15. Live worker state (`huddle_progress`)
- The owner cannot see what your workers are doing, so tell the huddle, not the terminal. When you start work on an item, set `huddle_update state: working`, then call `huddle_progress {item, phase, note?, worker?}` at each change: `queued`, `running`, `testing`, `installing`, `blocked` (say what you wait on in `note`), `done`. The item's row shows a small strip under its title: one line per worker (a phase chip, your note, the elapsed time); the open row shows the whole note.
- `worker` is your label ("orchestrator", "web", "api"). Each label keeps ONE line, replaced by its next call; up to 8 labels per item. Omit it for a single worker (label `main`).
- Keep `note` short, about 60 characters ("34 of 120 tests", "installing build 42"). It is a status line, not a report: results and questions still go to `huddle_reply` and `huddle_ask`.
- In a batch, use the op `progress` with `item_id`, `phase`, `note`, `worker`.
- A line with no update for 30 minutes shows dim as stale, and a line older than 6 hours is dropped. The lines live in memory only: after an app restart the strip is empty until you report again, so re-send your current phase after a restart.
- Do not spam it: one call per real change of phase or milestone.
