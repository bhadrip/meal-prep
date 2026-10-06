# Meal Prep backend

The backend owns Meal Prep use cases, authenticated household data, validation, Row-Level Security, MCP tools, MCP Apps, and the website. MCP and HTTP are transport adapters over the same application services.

```text
app/
├── application/       Use cases and product rules
├── infrastructure/    Supabase repository adapter
├── transports/        MCP BFF and HTTP routes
├── static/            Website, OAuth pages, and MCP Apps bundle
├── auth.py            Supabase token verification
├── container.py       Per-request composition
└── main.py            ASGI application
```

## What is included

- Getting-started landing page at `/` and manual app at `/app`, with household setup, weekly plan and rhythm, recipes and recipe sharing, pantry, shopping, feedback, reviews, memory, and dashboard settings
- Owner-managed invitations, multiple household memberships, and an active-household switcher
- A website notification inbox for invitations, membership, settings, plans, recipes, pantry, shopping, and reviews
- Authenticated JSON API under `/api` for the website and future mobile clients
- Streamable HTTP MCP endpoint at `/mcp`
- Domain tools for household context, preferences, recipes, pantry, meal plans, and shopping lists
- MCP Apps resources for household onboarding, the recipe library, the weekly plan, and the shopping checklist
- MCP-served onboarding for household constraints, planning coverage, preferred stores, cooking time, and leftovers
- Remembered weekly rhythms, meal and week feedback linked across recipes, variants, occurrences, weeks, and reusable tags, plus user-confirmed household preferences
- Supabase Auth bearer-token validation and OAuth 2.1 discovery through the MCP SDK
- Supabase schema, transactional functions, and RLS policies
- Private Supabase Storage bucket for compressed pantry photo evidence and a review gallery
- Pantry use records that subtract from remaining quantity, optionally name a meal or saved recipe, and drive a simple remaining-quantity bar
- Vercel serverless entrypoint and deployment configuration

MCP POST responses emit one JSON `mcp_response` entry in Vercel Runtime Logs.
Filter by that event and `rpc_method: "tools/list"` to see the exact outgoing
`tool_names`, `tool_count`, `save_recipe_present`, request/next cursor presence,
response bytes, SHA-256, HTTP status, and completion flag. The
`X-MCP-Request-ID` response header matches the log's `request_id`; an available
Vercel request ID is also included. Initialization identifies a client family;
`save_recipe` calls record success or tool error, without recipe contents.
Tokens, headers, RPC IDs, cursor values, tool arguments, and household responses
are never dumped. Capture is bounded; large responses are still sent in full
and logged with their byte count/hash and `response_capture_truncated: true`.

The website has no model integration. Users edit their data directly there. The service never calls a model to make domain writes. ChatGPT can create a plan through MCP, while Instacart or another commerce integration remains responsible for inventory, cart, and ordering actions.

Inbox entries are written by database triggers in the same transaction as household changes and are visible only to their recipient. Household entries become inaccessible when membership ends. The website loads the latest 100 entries when it opens or refreshes, and opening one marks it read and follows its destination. The database keeps at most 200 entries per person. There is no email, push, scheduler, or real-time subscription for this first version.

The website bootstraps household identity and invitations first. Its homepage then loads the current week's plan, shopping list, and pantry independently through selected snapshots, so one slow section does not block the others. Notifications load separately. Recipes, reviews, and the expandable household dashboard load when opened. `/api/app/snapshot` still returns all sections when no `sections` filter is supplied; `sections=mealPlan&week_start=YYYY-MM-DD` requests just a particular week's plan.

The website requests `/api/app/bootstrap?include_sections=false` for lightweight startup. The default bootstrap response retains all sections for older browser tabs.

## Deployed resources

Vercel's FastAPI framework forwards requests to `app.main:app` and preserves
their route paths without a catch-all rewrite. Keep `backend/vercel.json` free
of the old `/api/index` rewrite: current Vercel builds pass that destination to
FastAPI, causing both `/mcp` and `/api/health` to return 404. Verify a deployment's
health and MCP response before promoting it.

- Source repository: `https://github.com/bhadrip/meal-prep`
- Production app and MCP server: `https://meal-prep.madhavan-padmaja.dev`
- Supabase project: `svdcbpcndqmocecyymav` in `bhadrip's Org`

These resources are owned by the personal `bhadrip` accounts and are separate from Magik Mindz.

## Run locally

The normal local run uses Supabase Auth, its local Postgres database, and its Mailpit inbox. Install the [Supabase CLI and a Docker-compatible container runtime](https://supabase.com/docs/guides/local-development), then run:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
./scripts/dev-local.sh
```

Open `http://127.0.0.1:8000/` for the landing page, `http://127.0.0.1:8000/app` for the app, and `http://127.0.0.1:8000/api/health` to verify `persistence: supabase` and `auth_required: true`. Connect an MCP inspector or client to `http://127.0.0.1:8000/mcp`. The script reads the local anon key from `supabase status`; it does not store it in the repository. Stop the Python server with Ctrl-C and, when finished, stop the local containers with `supabase stop` from `backend/`.

### Test the shared login with local Supabase and Mailpit

The development script starts Supabase automatically. To inspect the local services separately, run from `backend/`:

```bash
supabase start
supabase status -o env
```

The local migrations initialize the database. If you run the Python server manually instead of using the script, copy the `API_URL` and `ANON_KEY` values reported by `supabase status -o env` into `backend/.env`:

```dotenv
APP_BASE_URL=http://127.0.0.1:8000
SUPABASE_URL=http://127.0.0.1:55321
SUPABASE_ANON_KEY=PASTE_LOCAL_ANON_KEY_HERE
AUTH_REQUIRED=true
```

Start the Python server with `uvicorn app.main:app --reload`. Open `http://127.0.0.1:8000/app` and request a sign-in code. The code appears in the local [Mailpit inbox](http://127.0.0.1:55324). Enter it to create an account and sign in, complete the household setup, and verify edits in the website and MCP client. Local mail is captured, not delivered externally. Meal Prep uses ports `55321`–`55324` so it can run beside other local Supabase projects. See [Supabase’s email testing guide](https://supabase.com/docs/guides/local-development/cli/testing-and-linting).

To test sharing locally, sign up and verify two accounts using their email codes in Mailpit. Give the second account its own household and save a recipe there. Sign in as the first user, open **Settings → Household members**, and enter the second account's email. Then sign in as the second user and select **Join household**. The shared household becomes active, while the second account's own household and recipe remain available from the top-bar switcher. Creating a household invitation sends no email and needs no server secret key.

If `supabase start` reports that Docker is unavailable, start the container runtime first. For a quick UI-only check without Supabase, leaving the Supabase values empty in `.env` still enables in-memory demo data; demo edits last only until the server restarts.

## Test and inspect

```bash
pytest
npx -y @modelcontextprotocol/inspector
```

Choose Streamable HTTP in the Inspector and use `http://127.0.0.1:8000/mcp`.

The browser suite runs complete website and embedded MCP App interactions in desktop Chrome, Android Chrome, and iPhone Safari emulation, with independent in-memory demo servers. It covers navigation, household settings, weekly planning, recipes and sharing, pantry, shopping, reviews, and sign-in UI with a mocked auth provider, plus touch targets, narrow/landscape layouts and editor resizing. See [`docs/test-coverage.md`](../docs/test-coverage.md) for the path inventory. From the repository root:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e 'backend[dev]'
pnpm install --frozen-lockfile
pnpm exec playwright install chromium webkit
pnpm test:ui
```

The `UI tests` GitHub Action runs the backend tests and Chromium suite on pull requests and pushes to `main`. The browser job uses demo data and simulated auth and chat hosts. Real Supabase sign-in through the browser and behavior inside a live MCP host require a separate integration environment.

The same workflow also starts a disposable local Supabase stack and checks an authenticated plan and weekly rhythm roundtrip against the actual migrations. To run that check locally after `supabase start`:

```bash
supabase migration up --local --workdir backend
backend/.venv/bin/python backend/scripts/test-local-supabase.py
```

`backend/scripts/dev-local.sh` applies pending local migrations at startup. The authenticated integration test creates and removes its own local test account and household. It does not connect to the production Supabase project.

## Supabase setup

1. Create a Supabase project.
2. Link the project and apply the checked-in schema:

   ```bash
   supabase link --project-ref YOUR_PROJECT_REF
   supabase db push
   ```

   For the Supabase GitHub integration, set **Working directory** to
   `backend` because the `supabase/` directory is nested in this
   repository. Enable **Deploy to production** if merges to `main` should apply
   new migrations automatically.

   Migration `202609300003` creates the private `pantry-evidence` Storage bucket,
   an RLS-protected evidence table, and household-scoped object policies. It
   stores one WebP copy per ChatGPT photo (maximum 1600 px on the longest side,
   without EXIF metadata). The original is not copied into Supabase. Review
   links are signed for one hour. If a photo was saved for review first, call
   `apply_pantry_evidence` after correcting the observed items.

   Supabase Free currently includes [1 GB of file storage](https://supabase.com/docs/guides/platform/billing-on-supabase)
   and [5 GB of egress](https://supabase.com/docs/guides/platform/manage-your-usage/egress).
   Free does not include hosted image transformations, so the backend makes a
   small WebP before upload. At an average 200 KB per photo, 1 GB holds roughly
   5,000 photos; actual capacity depends on image detail and other files in the
   project. There is no automatic deletion or retention limit.

3. In Authentication, enable email sign-up, set the Site URL to the Vercel production URL, and add `/login` as an allowed redirect. Set the email OTP length to eight digits and include `{{ .Token }}` in the Magic Link email template; the sign-in form expects that code. The checked-in local template configures this for local Supabase, while hosted projects need the same settings in the Supabase dashboard.
4. In Authentication > OAuth Server, enable OAuth 2.1, set the authorization path to `/oauth/consent`, and enable dynamic client registration.
5. Use an asymmetric JWT signing key (ES256 or RS256) so OAuth clients can validate tokens through JWKS.
6. Copy the project URL and anon key to `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Vercel.
7. Set `AUTH_REQUIRED=true` only after the consent screen and redirect URLs work.

The MCP resource advertises only `openid`, `email`, and `offline_access`.
It does not request profile or phone access. Codex loopback callbacks such as
`http://127.0.0.1:<port>/...` are generated by the OAuth client and must be
used unchanged while the corresponding Codex configure command is still running.

The first authenticated request creates an unconfigured household through `bootstrap_my_household`. It does not assume a household size, stores, cooking limit, or leftovers preference. The plugin opens the MCP-served onboarding form and marks onboarding complete only after the user submits it. Every subsequent database operation uses the caller's access token, so RLS remains the authority for ownership.

The owner can create a pending invitation only for an existing account with a verified email. No invitation email is sent. The invitee sees the invitation inside Meal Prep and must explicitly accept it. An account with a pending invitation and no household is sent to `/invite` before household bootstrap. Acceptance checks the signed-in account's verified email, adds membership, preserves all existing households and their data, and selects the joined household. The website switcher and MCP `list_households`, `switch_household`, and `create_household` tools manage multiple memberships. The saved active household is shared across website and MCP sessions; database row level security scopes data to that selection. Invitation and member changes run through checked database functions. Invitation records expire after seven days. Sharing itself needs no SMTP or server secret key. Because sign-up and sign-in currently use emailed one-time codes, those codes still need email delivery; Supabase's hosted default email service only sends to project team addresses, so external production accounts need [custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp) or a different sign-in method.

Removing a collaborator immediately removes their household membership and revokes recipe sharing links they created for that household. Other household data stays in place.

### Repair an existing project's migration history without a CLI

If the project schema was initially applied outside the migration runner, the
GitHub deployment may fail on migration `001` with an “already exists” error.
That means the database objects and `supabase_migrations.schema_migrations`
history disagree. Open the Supabase Dashboard's SQL Editor and run
[`supabase/manual/repair_initial_migration_history.sql`](supabase/manual/repair_initial_migration_history.sql).
Its preflight checks verify the tables, functions, grants, and onboarding
column from migrations `001`–`003` before it changes migration history. If a
check fails, stop and reconcile the missing schema instead of bypassing it.

After the repair succeeds, rerun the failed Supabase GitHub check or push the
next commit. The integration should skip `001`–`003` and apply the remaining
migrations in order.

Do not make migrations `004`–`008` applied unless their tables and indexes
already exist; those migrations must run before the feedback-consolidation
migration can preserve older weekly check-ins. A successful push should leave local and remote
columns aligned in `supabase migration list --linked`.

## Vercel setup

Create the Vercel project from the repository and set its Root Directory to `backend`. Configure:

```dotenv
APP_BASE_URL=https://meal-prep.madhavan-padmaja.dev
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
AUTH_REQUIRED=true
POSTHOG_PROJECT_TOKEN=YOUR_POSTHOG_PROJECT_TOKEN
POSTHOG_HOST=https://us.i.posthog.com
```

Set `POSTHOG_PROJECT_TOKEN` in the Vercel project’s Environment Variables for
Production (and Preview if desired), then redeploy. The US ingestion host is
the default, so `POSTHOG_HOST` is optional for a US project. Use the PostHog
project token, never a personal API key. The project token is sent to the web
client by `/api/auth/config`, as required for browser event capture. If the
token is unset, analytics is disabled and product actions continue normally.

PostHog uses the verified Supabase Auth user UUID as its `distinct_id` for both
web and MCP activity. The website records sign-in steps and app views, and
records masked session replays. The shared services record completed household,
planning, shopping, feedback, and memory actions from either entry point.
The MCP server also records tool listings and tool calls, including success and
duration. Every authenticated API write also records its route template,
method, status, and duration, including failed writes. Event properties exclude email, recipe, pantry, feedback, memory,
tool arguments, tool responses, and error messages. Session replay masks all
page text and inputs, blocks images and canvas content, and omits DOM attributes
and network bodies; navigation events provide the readable view names.

In PostHog, open **MCP analytics** for tool usage (`$mcp_tool_call` and
`$mcp_tools_list`); those events use PostHog's MCP event names without sending
tool arguments or results. Open **Activity** and filter by `entry_point` (`web`,
`mcp`, or future `ios`), then
open a person using the Supabase user UUID to see their cross-entry-point
timeline. Web actions and server events from that browser session share
`$session_id`; MCP requests with a transport session ID share a separate
hashed `$session_id`. Stateless MCP clients without a stable session header
still group by user but cannot be stitched into one conversation. Use
`request_id` to locate the corresponding MCP `mcp_response` record in Vercel
Logs. Vercel logs remain the source for HTTP status and server errors; PostHog
is for behavior and browser replay. A future iOS client should identify with
the same Supabase UUID, set `X-Meal-Prep-Client: ios`, and send its PostHog
session UUID as `X-PostHog-Session-Id` with API requests.

`APP_BASE_URL` is the public origin advertised by OAuth protected-resource
metadata and the landing page's MCP copy button. Use the same origin as
`plugin/mcp.json`; a Vercel deployment hostname and a custom domain are not
interchangeable OAuth resource identifiers. For another deployment, update both
the environment setting and the portable plugin endpoint.

Deploy, then verify:

- `GET /api/health` reports `persistence: supabase`.
- `/` provides the MCP URL and links to `/app`; `/app` redirects unsigned users to `/login`.
- Website edits appear through `/api/app/snapshot` and the MCP tools for the same account.
- `/login` can create a valid session.
- `/oauth/consent` displays an OAuth client request.
- MCP initialization and `tools/list` succeed at `/mcp` after authorization.

## Tool contract

Data tools:

- `get_household_context`
- `get_dashboard_layout`, `configure_dashboard`
- `get_planning_context`
- `get_meal_plan_rules`, `get_meal_plan_rule_history`, `save_meal_plan_rules`
- `update_household_preferences`
- `search_recipes`, `get_recipe`, `save_recipe`, `archive_recipe`
- `create_recipe_share`, `list_recipe_shares`, `revoke_recipe_share`, `copy_shared_recipe`
- `get_pantry`, `update_pantry_item`, `record_pantry_use`
- `save_pantry_photo`, `get_pantry_evidence`, `apply_pantry_evidence`
- `get_weekly_schedule`, `save_weekly_schedule`
- `get_feedback`, `save_feedback`, `get_what_worked`, `get_recipe_feedback_summary`
- `get_household_memory`, `save_household_memory`, `review_household_memory`
- `search_meals`, `get_meal`, `save_meal`, `archive_meal`
- `save_planned_meal`, `plan_saved_meal`, `render_meal_library`
- `save_meal_plan`, `get_meal_plan`
- `configure_meal_slots`, `update_plan_item`, `complete_plan_item`
- `preview_plan_shopping`, `save_plan_shopping`, `receive_shopping_item`
- `save_shopping_list`, `add_shopping_item`, `get_shopping_list`, `mark_item_purchased`

Presentation tools:

- `render_household_snapshot`
- `render_pantry_evidence`
- `render_recipe_library`
- `render_feedback`
- `render_onboarding`
- `render_meal_plan`
- `render_shopping_list`

## Meals and tasks

Reusable Meals are stored separately from Recipes and weekly-plan entries.
Recipes have `kind=recipe|ready_food`. Ready-food entries have preparation
instructions and no ingredient demand. Their meal components use `source=ready`
and may link to the library entry through `recipeId`. The same reference opens
details in the website and MCP App.

`/api/recipe-library?item_type=all|recipes|ready_food|meals` and
`browse_recipe_library(item_type=...)` share search and pagination. Recipe
filters also match recipes inside meals; they do not imply nutritional labels
for the entire meal.
`save_meal` requires a name, positive default servings, and 1–30 components
(`ready`, `cook`, `external`); cooking components reference active household
recipes. Library components have no task/pantry-lot IDs. `search_meals` searches
names, notes, and components, with `limit` 1–100 and `offset` 0–10000; archived
meals are excluded. `get_meal` also reads archived records for history.

`plan_saved_meal` adds an independent dated copy, scales component quantities
from default servings (rounding up to 0.001), snapshots current recipe
ingredients, and records `sourceMeal: {id, name, revision}`. Library edits and
archives preserve prior copies, which can still link actual stock or prep tasks.
`save_planned_meal` detaches those references, resolving recipe batches to cook
components. Missing plan servings default to 1; specify the quantity basis when
it is known. None of these operations changes inventory.

HTTP routes: `GET/PUT /api/meals`, `GET/DELETE /api/meals/{id}`,
`POST /api/meals/{id}/plan`, `POST /api/meals/from-plan`. The rendered MCP App
shares the Recipes library resource, with Recipes, Ready food, and Meals type filters, search, pagination, and a date/slot/servings form that
uses the same MCP tools. `render_recipe_library(item_type="meals")` selects
the Meals filter; `render_meal_library` is a convenience tool for that same
resource. `202610020002_reusable_meals.sql` adds the `meals`
table with RLS and JSON-reference validation, plus immutable plan provenance.
Fresh local Supabase tests verify the entire migration chain, foreign-household
rejection, direct-table validation, and edits after a library archive.

Household context exposes ordered `mealSlots` (`id`, `name`, `enabled`). The
website and MCP share `configure_meal_slots`; stable IDs survive renaming and
reordering, and disabling a slot preserves existing meals. Prep is a task.

`save_meal_plan` takes `weekStart`, `entries`, and `tasks`. Meals have stable UUIDs,
dates within the selected week, a household slot ID, `meal`, optional servings
and notes, and `components`. Components have UUIDs, a name, optional quantity/unit,
`source` (`ready`, `cook`, `task`, `external`), `action` (`cook`, `heat`, `serve`),
and optional `recipeId`, `pantryItemId`, or `taskId`. Cook components require a
recipe; task components require a task from the same plan. Tasks have a UUID,
title, optional date (including the preceding weekend), notes, optional recipe
and batch servings, and optional `mealIds`. No date, slot, or meal link is required
for a checklist task. `update_plan_item` patches one record and returns the plan.
The saved recipe ingredient/yield snapshot stays fixed through later recipe edits.

`preview_plan_shopping` calculates the selected week's remaining explicit demand.
It expands unfinished cooking tasks once, scales recipe components in servings,
and aggregates ready food before subtracting exact stock. It reports missing
amounts, uncertain stock, unknown conversions, and overallocated batch portions.
It supports explicit gram/kilogram and milliliter/liter conversions; packages are
not guessed. It does not reserve food or interpret English rules/notes. MCP should
reconcile other-week commitments and prose before saving the final list.
`save_plan_shopping` refreshes that week's pending generated lines, retaining
manual items and purchased history. Item `source.reasons` identifies its meals
or cooking tasks. The website exposes these operations through Shopping needs.

`complete_plan_item` atomically records a task completed or meal eaten. Explicit
inputs `{itemId, quantity}` consume actual quantities in each pantry item's unit;
outputs `{name, quantity, unit, storageLocation}` create prepared pantry lots.
No stock change is implied by a checklist. Each item has one immutable activity;
repeated or concurrent completion requests return its first result. Completed
items are history; correct pantry quantities separately if needed.
`receive_shopping_item` marks a line purchased and creates one pantry lot using
the actual received quantity/unit, safely on concurrent retries. The existing
purchase checkbox alone records shopping progress. Repeat purchases need separate
shopping lines. All stock/plan references are checked against the active household.

HTTP uses `PUT /api/meal-slots`, `PATCH /api/meal-plan/items`,
`POST /api/meal-plan/complete`, `GET /api/meal-plan/shopping-preview`,
`POST /api/meal-plan/shopping`, and `POST /api/shopping-list/receive`.
Migration `202610020001_unified_planning.sql` adds task/component storage, actual
activity, and receipt functions. Plan saves upsert meal entries rather than
recreating their IDs, preserving occurrence and feedback links. The MCP App renders
components and tasks and can record task/cooking/meal completion through data tools.

## English planning rules

Weekly plan has two tabs: **Plan** for the selected week’s meals, prep, and
temporary notes, and **Planning rules** for recurring English instructions and
version history. **Edit notes** changes only that week’s notes; **Edit weekly
rhythm** sets the pace for each day. The plan’s **Rules used: version N** link
opens its exact saved rules as a read-only document. Tab, week, and revision
links survive reload and browser navigation. On phones, day cards stack vertically.
Rules start empty. Each changed document creates an immutable household
revision; clearing the text preserves history. Saves include the revision
read by the editor so simultaneous changes cannot silently overwrite each other.

ChatGPT reads `get_planning_context(week_start=...)` before planning. The result
includes `mealPlanRules`, the current `mealPlan`, the two most recent earlier
saved weeks in `recentPlans`, `pantry`, `recipeTags`, schedule `notes`, feedback,
and household preferences. Candidate recipes and their lessons remain available
through recipe search and feedback tools. Recent plans describe what was planned;
feedback supplies evidence about what actually happened.

`save_meal_plan_rules(text, expected_revision)` saves the full English document;
pass 0 when none exists. `get_meal_plan_rules(revision_id=...)` reads an older
version and `get_meal_plan_rule_history` lists versions. Plans guided by a
document include `ruleRevisionId` when saved. Ordinary edits preserve that
source; later rule changes do not alter existing plans. Migration
`202610010003_meal_plan_rules.sql` installs the storage and history functions.

ChatGPT interprets the English instructions and proposes a plan for review.
The service stores data and checks identifiers and revisions; it does not
evaluate a rule language or generate meals.

## Boundaries

- Demo mode is intentionally in memory; production MCP data is durable in Supabase.
- The plugin stores plans and shopping lists but never places orders. Commerce remains a separate, explicitly confirmed tool flow.
- The service does not provide medical guidance or fabricate food-safety dates.
- Recipe shares publish a fixed, allowlisted snapshot at `/s/{token}`. Anyone with the active link can view it; signed-in users can save an independent copy. Share creation requires a household recipe, and the URL is returned only once. The creator can list and revoke links. Shares omit cooking feedback and household details.

### Shared MCP workflow instructions

`app/transports/meal-prep-instructions.md` is the canonical planning workflow.
The server returns it in the MCP `initialize` response, including for direct
OAuth connections without the plugin. The plugin skill is only an entry point.
Edit the server document when changing workflow guidance. MCP Apps enhance
presentation; clients without app rendering can use structured results and
complete onboarding conversationally. Photo archival still requires a supported
ChatGPT attachment; moving instructions does not add other clients' upload formats.


## Chat website revamp

Apply `supabase/migrations/202610050001_chat_revamp.sql` **before** deploying the chat revamp. The migration preserves existing circles, posts and frozen recipients while adding private profiles, read/mute state, reactions, idempotent sends and caller-scoped live versions. New operations are exposed through shared application services and both HTTP and direct MCP tools; no plugin installation is required.

The website consumes bounded authenticated SSE invalidations and rechecks history through the same authorization RPCs. Direct shares with the same accepted friend reuse one conversation; legacy direct-room posts keep their original membership epochs. Read [chat layout, delivery and verification](../docs/circles-performance.md) for the transport, paging and privacy details.

Local verification runs the complete backend suite and Chromium/Android/iPhone Playwright matrix. The Supabase integration suite additionally exercises concurrent retries/direct shares, removed and re-invited members, legacy-room consolidation, muted notifications and account cleanup against a disposable local stack. It does not require or modify production data.
