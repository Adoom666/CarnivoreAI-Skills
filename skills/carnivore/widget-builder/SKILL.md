---
name: widget-builder
description: How to build a new Carnivore dashboard widget end to end (named sizes, cell, manifest, push data source, fixtures, fit harness, style guide, i18n, pop-out, feature catalog, ratchets). Use when asked to "build a widget", "new dashboard widget", "add a widget", "make a home cell", or when changing any file under web/src/opscenter/widgets or web/src/opscenter/cells.
---

# widget-builder: ship a widget that fits every size it names

Repo: the Carnivore source checkout (use a separate worktree only when a parallel worker needs isolation). Read `docs/widget-spec.md` sections 1, 6 and 10 once before you start; this skill is the order of work, that file is the rule book. Where the two disagree, the code wins (see "Stale spots" at the end).

Reference widgets to copy, never invent:
- Simple, pushed, two layouts: `web/src/opscenter/cells/machine-stats/` (`Cell.svelte`, `meta.ts`, `store.svelte.ts`, `Cell.test.ts`), route `src/api/machine_stats_routes.py`, sampler `src/core/machine_stats/`.
- Even simpler: `web/src/opscenter/cells/keep-awake/`.
- Chart family: `web/src/opscenter/cells/analytics/` plus renderer facts in `web/src/opscenter/viz/specs.ts` (`VIZ_SPECS[viz].min` is the renderer's floor).
- Width ladder worked example: `web/src/opscenter/cells/activity-log/Cell.svelte`.

## 0. Before any code
- Feature or real bug: run the repo's work-skill intake (`.claude/skills/work/SKILL.md`), search issues, file or reuse one. Tell the owner which backend/data source you will use if it needs a new server route.
- Lean pipeline (CLAUDE.md): worktree only if a parallel worker needs one, ONE test that matters, push by explicit path. The full harness matrix is the exception for widgets: step 5 is required.
- Read the style guide (`client/style-guide.html`, sections under `client/style-guide/sections/`, especially `18-cells.html`) and the closest worked example above.

## 1. Pick or declare the named sizes
Sizes are NAMES, never numbers, in every menu, plate and spec (a standing ruling: hide the numbers for the size). The names and their grid units (96 x 64 px per unit) live in `web/src/opscenter/widgets/named-sizes.ts` (`NAMED_SIZE_UNITS`):

| Name | Units | Box | What the widget must show there |
|---|---|---|---|
| `small` | 1 x 1 | 96 x 64 | one number or state, no label if it will not fit |
| `wide` | 2 x 1 | 192 x 64 | number plus its label, or one short line |
| `tall` | 2 x 4 | 192 x 256 | a short list or a stack of numbers |
| `medium` | 4 x 4 | 384 x 256 | a list with a few rows, or a small chart |
| `large` | 6 x 5 | 576 x 320 | a list with its columns, a chart with its axis |
| `full` | 12 x 5 | 1152 x 320 | every column, a long timeline, a pane |
| `glance` | px height | 64 x 36 tile | optional, section 8 of the spec; a glance-row tile |

Rules:
- Declare only names you will pass the fit check at. Machine stats declares `tall, medium, large, full`; keep-awake `tall, medium, large`; the stat tiles `small, wide`.
- `anySize: true` means the body also fills any box from its floor up (every built-in says this, so the widget must lay out for ANY box, not just the names). `anySize: false` means a box outside the names' span draws the not-available plate (`fits.ts::testedBox`, 25 percent tolerance on width, height and aspect).
- The floor (`minPx`, `minHeight` on the cell record) is yours to choose; it is the one hard limit. Make it at least the smallest named size you declare. Below it, `checkFit` answers `too-small` and the plate draws.
- For each declared name write down, in the cell's header comment, what it shows (the table above is the minimum). Drop detail as the box shrinks; never shrink type below the theme sizes.

## 2. File layout and registration
One new cell id `<id>` (kebab-case). Touch exactly these, in this order (copy machine-stats line for line, `grep -rn "machine-stats" web/src` lists them):

1. `web/src/opscenter/engine/types.ts`: add `'<id>'` to the `CellId` union.
2. `web/src/opscenter/engine/meta.ts`: add the `META['<id>']` record: `titleKey`, `icon`, `iconTone`, `chrome`, `titleHeight`, default row/index/fr/height, floors `minPx` and `minHeight`, `widthStates`, `heightStates` (the density ladders, step 4).
3. `web/src/opscenter/engine/model.ts`: add to `HIDDEN_BY_DEFAULT` if it must not appear in saved layouts until placed (new widgets should; no saved layout may move).
4. `web/src/opscenter/cells/<id>/`: `Cell.svelte`, `meta.ts` (re-exports `metaFor('<id>')` and pure reading code), `store.svelte.ts` (step 3), `Cell.test.ts`.
5. `web/src/opscenter/cells/registry.ts`: import the component, add `'<id>': { meta: META['<id>'], component: ... }` plus title-row hooks if it has a count (`titleCount`, `phoneTotal` from its `meta.ts`).
6. `web/src/opscenter/widgets/core-manifests.ts`: add `EXTRAS['<id>']` with `category` (`overview`, `sessions`, `catalog`, `monitoring`, `tools`, `live`), `type` (`kpi`, `list`, `monitor`, `feed`, `tool`, `pane`, `chart`), `capabilities` (`[]` when it only reads).
7. `src/data/widgets.json`: add the row `{ "id": "core.<id>", "instancing": "singleton", "fits": { "sizes": [...names...], "anySize": true, "max_per_surface": 1 } }`. A cell with no row throws at load (`widgets/fit-declarations.ts`). A glance size is `"glance": { "height": 36 }` and needs `registerGlance` in `web/src/lib/drawer-zone/glances.ts`.
8. `web/src/opscenter/widgets/fixtures/core.<id>.ts` and its line in `widgets/fixtures/index.ts` (step 5).
9. i18n keys, style guide, catalog, tests (steps 6, 7, 9, 10).

A third-party or plugin widget does not edit 1 to 3, 5, 6: it goes through the cplug seam (`docs/cplugs.md` section 2.7, `docs/cplug-platform.md`, first example `huddle.chat`): the `widgets.<name>` block in its `cplug.json` carries the `widgets.json` row, and the web contribution is `CplugWidget { name, meta, component, extras }` registered by `web/src/cplugs/host/widgets.ts`. Plugins still need fixtures and the same fit pass.

## 3. Data source: one authenticated route, one push topic, no timer
PUSH, NOT PULL is the standing performance rule (CLAUDE.md, `docs/DECISIONS.md`): zero timed polling at idle, one broadcast per update, the backend orchestrates.

1. Every action and read is a documented, authenticated route (`Depends(require_auth)`), mounted in `src/api/routes.py` (an aggregator: add only the import and `include_router` lines). Model: `src/api/machine_stats_routes.py`. Unmeasured values are `None`, never zero.
2. A new topic: add a constant in `src/core/resource_push/topics.py` and its tuple entry. ADDING A TOPIC IS A PROMISE THAT EVERY WRITER OF THAT RESOURCE CALLS `resource_push.notify(<topic>)` at its one mutation point (clients stop polling for any advertised topic). Compare `src/core/machine_stats/watch.py` (viewer-gated: nothing samples with no viewer).
3. Client store: build it on `resource(...)` from `web/src/opscenter/api/poll.svelte.ts` with `topics: [TOPIC]`, as `cells/machine-stats/store.svelte.ts` does: `authFetch`, fallback `intervalMs` that runs only while the push is down, a `demo` answer, a hidden tab reads nothing, the store exists only while a cell is mounted (`acquire` in `$effect`, release on teardown).
4. Reuse an existing pushed store when one exists (listing: `window.ListingPush`; ledger; approvals). Never add a second read of the same data.
5. Server tests: `tests/python/<area>/test_<id>.py` (see `tests/python/machine_stats/test_machine_stats.py`): route shape, auth refusal, notify on every writer.

## 4. Renderer and floors per size
- The cell receives `{ width, height, meta }` in px (`web/src/opscenter/lib/cell.ts::CellProps`) measured by the host. Never read the window.
- Ladders, not px branches: declare `widthStates` and `heightStates` on the META record; pick with `pickState(meta.widthStates, width, previous)` (`web/src/opscenter/lib/states.ts`, 12 px hysteresis) and branch by step name. Width in CSS: `@container oc-cell (max-width: ...)`. Height is not a container axis, use the height ladder.
- Layout rules that make any box safe: `min-width: 0` on every flex or grid child holding text; one long line gets `overflow: hidden; text-overflow: ellipsis; white-space: nowrap` (the fit check accepts only an ellipsis); lists scroll vertically inside the body; a sideways scroller says `data-fit-scroll-x`; a deliberate clip says `data-fit-clip`.
- Floors: the cell's `minPx`/`minHeight`; a chart's renderer floor is `VIZ_SPECS[viz].min` (`viz/specs.ts`) and a preset drawn below it shows the plate, not a slipping chart. The floor must hold at the smallest declared name, with the title row (`titleHeight`) counted.
- Empty state: one calm muted line naming what will appear and when (shared `EmptyState.svelte` or a catalog line), never a big "no data" headline, never zeros standing in for unmeasured. Loading and signed-out are sentences, as machine stats does.
- Military Terminal look (CLAUDE.md, "Every UI surface wears the Military Terminal look"): `--oc-*` tokens only, `--font-mono`, tracked uppercase labels, 1 px hairlines, square corners, one accent. Copy `cells/machine-stats/Cell.svelte`'s `<style>` shape (`@layer components`). No raw px for padding, margin, gap or font size when a scale token exists; no hex, rgb or named color.

## 5. Fit tests at every declared size
The harness (`docs/widget-spec.md` section 6; commit 764f9a0ff) draws the REAL cell host and frame from a made-up fixture: `Date` pinned to the frozen clock (`widgets/fixtures/clock.ts`, `ago(seconds)`), `fetch` under `/api/` answered from the fixture route table, `WebSocket` that never opens. A route the widget asks that the fixture does not answer is recorded as a FIXTURE MISS and fails.

What it does to your widget (`web/src/widget-harness/fit-probe.ts`, `web/src/opscenter/widgets/standard-sizes.ts`): draws it in home, terminal, sidebar widget area and glance row, at `s` (the floor), `m`, `l`, `phone`, EVERY named size you declared, and three odd boxes (`odd-wide`, `odd-tall`, `odd-mid`), under three themes, with `data` and `empty`, settled (fonts loaded, 600 ms quiet, reduced motion). Findings that fail: `overflow-x`, `overflow-y`, `scrollbar-x`, `clipped-text` (no ellipsis), `overlap`, `bad-text` (unknown, undefined, NaN, raw ids), `catalog-key` (a visible missing translation). ANY finding fails. Fix the widget's layout; never loosen the check; never narrow the claim to dodge a real bug (narrowing is allowed only honestly, by dropping a name from `fits.sizes` and setting `anySize: false`).

Write the fixture: `web/src/opscenter/widgets/fixtures/core.<id>.ts` exports a `WidgetFixtures` pair `{ data, empty }` (types in `fixtures/types.ts`, example `fixtures/core.machine-stats.ts`): a route table such as `'GET /machine-stats'` to the JSON the server answers; made-up names; times as offsets from the frozen clock; no randomness; `empty` is the real calm empty state, not an error. Register it in `fixtures/index.ts` `TABLES` (a widget with no fixture makes capture exit 1).

Run it (from the repo root; a fresh worktree has no `venv`, so point `venv/bin/python3` at the main checkout's venv and give the worktree its own real `web/node_modules` via `npm ci`, never a symlink):
```
venv/bin/python3 -m scripts.widgets.capture --only core.<id> --themes carnivore   # fast geometry pass
venv/bin/python3 -m scripts.widgets.capture --only core.<id>                       # all three themes, before landing
```
Exit 0 is the only pass; 1 is a finding or a missing fixture; 2 means it could not run (never a pass). Read `build/widget-capture/report.md` (element, px slipped, screenshot). Options: `--fixtures data`, `--zones home`, `--sizes s,m,glance,odd-wide`, `--no-shots`, `--catalog` (writes the description images to `features/media/widgets/<key>/`). Open one draw by hand: `/static/widget-harness-build/index.html?widget=core.<id>&zone=home&size=medium&fixture=data&theme=carnivore`. Limit to two test-heavy workers at once (CLAUDE.md); read `sysctl -n vm.loadavg` first.

Unit-level companions: `widgets/not-available.test.ts`, `widgets/standard-sizes.test.ts`, `widgets/fits.contract.test.ts`, `widgets/any-size.test.ts`, `widgets/chrome/resize-hint.test.ts`, plus your `Cell.test.ts` rendering the cell at each named size's px (see `cells/machine-stats/Cell.test.ts`).

## 6. Style guide entry and tokens
- Every new class or Svelte component needs a guide entry IN THE SAME CHANGE: file and classes under the right section in `client/style-guide/registry.json` (machine stats is under `section: "cells"`), prose in the fragment (`client/style-guide/sections/18-cells.html`, add an `<h3 class="sg-h3" id="cells-<id>">` block like `cells-machine-stats`: what it shows, declared sizes, topic).
- `venv/bin/python3 -m tests.helpers.style_guide_inventory` prints the gap; `tests/test_style_guide_drift.py` fails on either direction.
- Tokens: `--oc-*` from `web/src/opscenter/tokens.css`; status in `--oc-cyan/yellow/coral` etc.; verify under at least two other shipped themes with different accents (the harness's three capture themes are in `web/src/widget-harness/themes.ts`). Buttons copy `.modal-btn` / `.oc-btn`; do not add a new `*btn*` base class (`tests/python/design_system/test_no_new_button_family.py`). Focus comes from the one shared rule `web/src/opscenter/focus.css`.

## 7. i18n keys
- One catalog, `client/js/i18n/catalog.en.js`; flat dotted keys that name MEANING; data not code (no functions or template literals). Svelte reads `t('key', { name: value })` from `web/src/lib/i18n/index.svelte.ts`. A missing key renders the key itself and the harness fails it as `catalog-key`.
- Key set per widget: `opscenter.cell.<id>.title` (the record's `titleKey`), `opscenter.<id>.loading`, `.signed_out`, `.error`, one per label and unit (see the `opscenter.machine_stats.*` block, around line 4297). The manifest's `type` needs `widgets.type.<type>` (already there for the seven types). UI copy is lowercase, plain, US spelling.
- Words that are data (account names) go through an `optionLabel`, not the catalog.

## 8. Pop-out support
Every singleton may open alone in its own window: `client/popout.html?widget=core.<id>` renders `web/src/popout/SingleWidget.svelte`, which uses the registry's own component, so a cell that reads only its pushed store works with no extra code. It never writes the Home layout, opens no socket but `/ws/events`, and sizes the window from the widget's largest declared size (`web/src/popout/popout.ts::openWidgetPopout`). Your checks: nothing in the cell assumes the home grid, a terminal, or a layout write; it renders under `SingleWidget` (add a case to `web/src/popout/widget-popout.test.ts` modeled on the machine-stats one). The gear menu's "pop out" item appears from the manifest, no wiring. Plugin widgets: `docs/cplugs.md` 2.7 (pop-out ship list `web/src/cplugs/popout.ts`).

## 9. Feature catalog plus capture
A new widget is a product change (CLAUDE.md "Every product-changing change"):
- `features/catalog/<id>-widget.json`: id, name, summary, description, `area`, `status`, `surfaces`, `api_routes`, `docs`, `issues`, `keywords`, `where`, `how_to`, `examples`, and `media` or `media_exempt` (copy `features/catalog/machine-stats-widget.json`).
- `features/changes/<date>-<slug>.json` (copy `features/changes/2026-10-01-machine-stats-widget.json`; `type: "added"`).
- `features/capture/<id>-widget.json`: the steps that regenerate its image (copy `features/capture/keep-awake-widget.json`: seed, goto, add from the Components list, target `.oc-frame[data-cell='<id>']`). Images are reproduced by `python3 scripts/feature_capture.py <id>-widget` against a leased test slot, never hand-taken. Capture and `scripts/features.py check` run only right before a version bump; commit the capture JSON now.
- Never hand-edit `FEATURES.md`, `features/index.json`, `features/schema.json`, and never stage `client/dist` on a branch.
- Name the push topic in the cell's header comment and in the catalog entry (spec section 1).

## 10. The exact test commands
Python from the repo root with the repo venv; web from `web/` (`npm ci`, never `npm install`).
```
cd web && npx vitest run src/opscenter/widgets src/opscenter/cells/<id> src/popout src/lib/i18n
cd web && npm run check && npm run build            # build only because web/ changed
venv/bin/python3 -m pytest -q tests/python/widgets tests/python/design_system tests/python/drawer
venv/bin/python3 -m pytest -q tests/python/ui_preferences/test_ui_preferences_widget_fits.py tests/python/<area>
venv/bin/python3 -m pytest -q tests/test_style_guide_drift.py tests/test_docs_index.py
venv/bin/python3 -m scripts.widgets.capture --only core.<id>         # step 5, must exit 0
python3 scripts/js_syntax_check.py <any client/js file you touched>
```
The two ratchet directories are the design gate: `tests/python/design_system` (layers, scale tokens, no new button family, tooltips only on icon-only controls, scrollbars reachable) and `tests/python/drawer`. Ratchets only fall; a failure means fix your code, never raise the allowance. A failing test is rerun once, alone. `tests/python/widgets/test_widget_fit_check.py` is the negative control proving the check can go red; the whole matrix runs with `CARNIVORE_WIDGET_FIT=1` (about an hour, pre-bump only).

## 11. Done checklist
- [ ] Sizes named in `src/data/widgets.json`; header comment says what each shows; floor holds at the smallest.
- [ ] Cell registered in types, meta, model (hidden by default), registry, core-manifests.
- [ ] Data: authenticated route, topic constant, every writer notifies, store on `resource(...)`, no timer, no zero-for-unmeasured.
- [ ] Fixture pair registered; capture `--only core.<id>` exits 0 with all three themes, data and empty.
- [ ] Cell test at each named size; `vitest` widgets and popout suites green; `npm run check` clean.
- [ ] All colors `--oc-*`, scale tokens, `@layer components`, ellipsis on long lines, `min-width: 0`.
- [ ] Style guide registry and fragment updated; drift test green.
- [ ] i18n keys added, none shown raw.
- [ ] Renders in the pop-out; writes no layout.
- [ ] `features/catalog`, `features/changes`, `features/capture` files added; no generated file edited.
- [ ] `tests/python/design_system`, `tests/python/drawer`, `tests/test_docs_index.py` green.
- [ ] Docs updated in the same change (`docs/widget-spec.md` if a rule moved, `docs/INDEX.md` row for any new doc); security review run; commit by explicit path; push only through the repo's pipeline and only when the owner says so.

## Mistakes we've made (do not repeat)
- **Resize hint flip.** The guide aimed at a box grown to the floor, not a declared size, so chevrons pointed at a size no row could reach and flipped drag-right to drag-left. Fixed in `widgets/chrome/resize-hint.ts`: the target is always a declared size the box can reach, held until another is nearer by `SWITCH_MARGIN` (2 units). Keep your floors and names honest or the guide misleads; never write a widget-local hint.
- **Names that fall below their own floor.** The first named sizes were one or two rows tall, so lists showed a header and no rows and charts drew the plate at every size they declared. A declared name must be at or above the floor and tall enough for what it claims (chart renderer floor `VIZ_SPECS[viz].min`, measured WITH the title row).
- **Renderer floors measured on the body only.** A chart's floor was compared without its title row and rounded down to "arrived" 13 px short. Count `titleHeight`.
- **Raw px and color literals.** Padding, margin, gap on the 4/8/12/16/24/32 scale or 10/11/12 px fonts must be tokens; hex, rgb() and `var(--color-*)` are refused by the ratchets (`tests/python/design_system`). Rules outside `@layer components` raise the unlayered count.
- **Timer polls.** The save pipeline widget's 15 s poll is on the conversion list. A widget that polls needs a server push first.
- **Topic without every writer.** A topic advertised in `events.hello` makes clients stop polling it; a writer that forgets `notify` leaves widgets stale with no error.
- **Zero standing in for unmeasured.** Print the not-measured words; the server answers `None`.
- **A chart drawn at a size nobody declared.** Every built-in is `anySize`, so the plate disappears at the floor and the body must fill the odd box (`odd-wide`, `odd-tall`, `odd-mid`); test those, not just the names.
- **A foot bar measured one frame late.** `TerminalFoot.svelte` re-measured only on a ResizeObserver tick, so a content flip overran the bar by 71 px intermittently at terminal `s`; any measuring copy must re-measure in the same flush as its content.
- **Fixture misses and clocks.** A route the widget asks but the fixture lacks, `Math.random`, `new Date()` outside the frozen clock, or a real id (not made up) fail or flake the harness.
- **Tooltips on titles and names** (`test_tooltips_icon_only.py`): only icon-only controls get one.
- **A new `*btn*` base class** is a 33rd button family; reuse `.oc-btn` / `.modal-btn`.
- **Retired fit keys.** `zones`, `suggested`, `tested`, `allowed`, `max` in a declaration are refused by name (`widgets/fit-declarations.ts`); use `fits.sizes` and `anySize`. `max_per_surface` on a singleton can only be 1.
- **A glance renderer with no glance declaration** is refused (logged); declare `glance.height` first.
- **A symlinked `web/node_modules`** empties the real one on `npm ci`; each worktree gets its own copy (CLAUDE.md).
- **Stale doc.** Update `docs/widget-spec.md` in the same change (gotcha 8).

## Stale spots (code wins)
`docs/widget-spec.md` sections 1, 5, 6 and 10 still say `fits.tested` and the `u<w>x<h>` standard sizes in places; the live declaration is `fits.sizes` (names) plus `anySize` (`widgets/fit-declarations.ts`, `named-sizes.ts`). Fix the doc line you hit, in the same change.
