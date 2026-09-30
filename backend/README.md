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

- Manual website at `/` and `/app`, with household setup, weekly plan and rhythm, recipes and recipe sharing, pantry, shopping, feedback, reviews, memory, and dashboard settings
- Owner-managed household invitations and shared adult access from website Settings
- Authenticated JSON API under `/api` for the website and future mobile clients
- Streamable HTTP MCP endpoint at `/mcp`
- Domain tools for household context, preferences, recipes, pantry, meal plans, and shopping lists
- MCP Apps resources for household onboarding, the recipe library, the weekly plan, and the shopping checklist
- MCP-served onboarding for household constraints, planning coverage, preferred stores, cooking time, and leftovers
- Remembered weekly rhythms, meal and week feedback linked across recipes, variants, occurrences, weeks, and reusable tags, plus user-confirmed household preferences
- Supabase Auth bearer-token validation and OAuth 2.1 discovery through the MCP SDK
- Supabase schema, transactional functions, and RLS policies
- Vercel serverless entrypoint and deployment configuration

The website has no model integration. Users edit their data directly there. The service never calls a model to make domain writes. ChatGPT can create a plan through MCP, while Instacart or another commerce integration remains responsible for inventory, cart, and ordering actions.

## Deployed resources

- Source repository: `https://github.com/bhadrip/meal-prep`
- Production app and MCP server: `https://meal-prep-swart.vercel.app`
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

Open `http://127.0.0.1:8000/` for the website and `http://127.0.0.1:8000/api/health` to verify `persistence: supabase` and `auth_required: true`. Connect an MCP inspector or client to `http://127.0.0.1:8000/mcp`. The script reads the local anon key from `supabase status`; it does not store it in the repository. Stop the Python server with Ctrl-C and, when finished, stop the local containers with `supabase stop` from `backend/`.

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

Start the Python server with `uvicorn app.main:app --reload`. Open `http://127.0.0.1:8000/` and request a sign-in code. The code appears in the local [Mailpit inbox](http://127.0.0.1:55324). Enter it to create an account and sign in, complete the household setup, and verify edits in the website and MCP client. Local mail is captured, not delivered externally. Meal Prep uses ports `55321`–`55324` so it can run beside other local Supabase projects. See [Supabase’s email testing guide](https://supabase.com/docs/guides/local-development/cli/testing-and-linting).

To test sharing locally, sign up and verify two accounts using their email codes in Mailpit. Give the second account its own household and save a recipe there. Sign in as the first user, open **Settings → Household members**, and enter the second account's email. Then sign in as the second user and select **Join household**. The shared household becomes active, while the second account's own household and recipe remain available from the top-bar switcher. Creating a household invitation sends no email and needs no server secret key.

If `supabase start` reports that Docker is unavailable, start the container runtime first. For a quick UI-only check without Supabase, leaving the Supabase values empty in `.env` still enables in-memory demo data; demo edits last only until the server restarts.

## Test and inspect

```bash
pytest
npx -y @modelcontextprotocol/inspector
```

Choose Streamable HTTP in the Inspector and use `http://127.0.0.1:8000/mcp`.

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
APP_BASE_URL=https://YOUR_PROJECT.vercel.app
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
AUTH_REQUIRED=true
```

Deploy, then verify:

- `GET /api/health` reports `persistence: supabase`.
- `/` opens the website and redirects unsigned users to `/login`.
- Website edits appear through `/api/app/snapshot` and the MCP tools for the same account.
- `/login` can create a valid session.
- `/oauth/consent` displays an OAuth client request.
- MCP initialization and `tools/list` succeed at `/mcp` after authorization.

## Tool contract

Data tools:

- `get_household_context`
- `get_dashboard_layout`, `configure_dashboard`
- `get_planning_context`
- `update_household_preferences`
- `search_recipes`, `get_recipe`, `save_recipe`, `archive_recipe`
- `create_recipe_share`, `list_recipe_shares`, `revoke_recipe_share`, `copy_shared_recipe`
- `get_pantry`, `update_pantry_item`
- `get_weekly_schedule`, `save_weekly_schedule`
- `get_feedback`, `save_feedback`, `get_what_worked`, `get_recipe_feedback_summary`
- `get_household_memory`, `save_household_memory`, `review_household_memory`
- `save_meal_plan`, `get_meal_plan`
- `save_shopping_list`, `add_shopping_item`, `get_shopping_list`, `mark_item_purchased`

Presentation tools:

- `render_household_snapshot`
- `render_recipe_library`
- `render_feedback`
- `render_onboarding`
- `render_meal_plan`
- `render_shopping_list`

## Boundaries

- Demo mode is intentionally in memory; production MCP data is durable in Supabase.
- The plugin stores plans and shopping lists but never places orders. Commerce remains a separate, explicitly confirmed tool flow.
- The service does not provide medical guidance or fabricate food-safety dates.
- Recipe shares publish a fixed, allowlisted snapshot at `/s/{token}`. Anyone with the active link can view it; signed-in users can save an independent copy. Share creation requires a household recipe, and the URL is returned only once. The creator can list and revoke links. Shares omit cooking feedback and household details.
