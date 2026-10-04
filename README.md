# Meal Prep

Meal Prep is a household food-planning app available as a website and a hosted MCP service. It coordinates breakfasts, lunches, dinners, snacks, weekend prep, pantry inventory, and store-prioritized shopping around a family’s actual week.

The website offers direct, manual access to household setup, planning, meals, recipes, pantry, shopping, and feedback. The installable plugin supplies workflow guidance and the MCP connection. Both use the same application services and Supabase household data. The website has no AI features.

**Recipes** is one searchable library with an All view and type filters for
Recipes, Ready food, and Meals. Save one
or several recipes with ready food, such as dal + pre-cooked rotis + yogurt,
with default servings and notes. Search names, notes, and components across the
whole library. **Save as meal** is available on a recipe or weekly-plan entry;
**Use saved meal** adds a dated copy to the selected week. Component amounts
scale with servings. The copy retains the saved meal's ID/name/revision and
recipe ingredient snapshots, so editing or archiving the library meal leaves
existing plans intact. Pantry lot and batch-task links belong to the dated copy.
Ready foods use `save_recipe` with `kind="ready_food"`; their preparation notes
are instructions, and shopping demands the food itself rather than ingredients.
Meal components link to either kind of library entry and open its details.

MCP exposes the same filter through `render_recipe_library(item_type="meals")`
(or `render_meal_library`), with
`search_meals`, `get_meal`, `save_meal`, `archive_meal`, `save_planned_meal`, and
`plan_saved_meal` available without UI. The additive migration
`202610020002_reusable_meals.sql` installs household-scoped storage and plan
provenance. Supabase's GitHub integration applies it after merge through the
existing deployment workflow; GitHub Actions tests migrations on a disposable
local database.

Households configure their ordered eating occasions in **Settings → Meal slots**.
The weekly plan keeps dated meals separate from tasks. Meals can combine bought
food, recipes, and food prepared by a task; popcorn or pre-cooked rotis need no
recipe. Tasks support optional dates, recipes, batch servings, notes, and meal
links. **Shopping needs** scales explicit quantities, counts each linked batch
once, subtracts exact stock once, and reports missing quantities or conversions.
Review other-week commitments and English notes before saving the suggestions.
Manual shopping items and purchase history survive regeneration.

Planning leaves inventory unchanged. **Add to pantry** on a shopping line records
the quantity actually received. **Record cooking** and **Record eaten** record
actual food used and prepared stock remaining; ordinary tasks are checklists.
Each receipt/completion can be retried without adding or consuming stock twice.
Apply `202610020001_unified_planning.sql` after the existing migrations to enable
the shared website and MCP storage.

The website also has a personal notification inbox for household invitations and activity. Alerts stay in the website; they do not send email or push messages. The inbox shows activity from households you still belong to, and opening an alert switches to its household when needed and marks it read. You can also mark notifications read or unread, archive them to clear the inbox, and restore them from View archive. Direct MCP clients have the same list, read, and archive operations.

```text
Website           → HTTP API ─┐
Codex / ChatGPT   → MCP BFF ──┼→ application services → Supabase
Future mobile app → HTTP API ─┘
```

## Website

Open the [Meal Prep landing page](https://meal-prep.madhavan-padmaja.dev/) and choose **Open the app**, or go straight to `/app`. Sign up or sign in with the same Supabase email used for the MCP connection. Browser and MCP clients have separate sessions, but they share the same identity and active household. The app supports manual edits and never places grocery orders.

In **Recipes**, start with a cuisine, eating goal, meal, diet, or saved tag. Filters combine across groups (for example, protein rich + dinner), with alternatives within a group. Search includes ingredients, and cooking time filters require a saved total time. Filters stay in the website URL through recipe detail and reload; **Show more recipes** continues beyond the first 25.

**Explore these results** starts collapsed whenever the website opens or reloads; opening it stays a session choice and does not change the URL. Expand it below the result count to see the clickable graph alongside your recipe cards. It follows the current search and filters across all matching recipes, including those beyond the first card page. Direct variations and serving partners outside the filters are labeled **Related recipe**. Use the main recipe search and select **Explore** on a result card to start from that dish. Follow a dish or category in the graph, and use **Add detail** or select an edge to edit it. The editor can link any active recipe in the household. **Variation of** points to the base recipe; **Serve with** works in either direction. Recipe cards with variations open that neighborhood in the same panel. Undo reverses the last graph change during the session. Categories can also be edited in **Edit recipe** and immediately affect browsing.

Chat uses the same data through `render_recipe_library`, `browse_recipe_library`, `get_recipe_graph`, `render_recipe_graph`, and the relationship tools. Graph tools accept the same search, filters, and cooking time constraints as browsing and distinguish matching recipes from related ones. Eating goals and diets are household-entered categories, not verified nutrition. Existing tags are preserved; they are not automatically reclassified.

Apply `202610010005_recipe_relationships.sql` followed by `202610010006_recipe_browsing.sql` for graph relationships and browsing categories in Supabase.


For local demo mode or a full local Supabase and email flow, see [`backend/README.md`](backend/README.md#run-locally).

## Access

Each person signs in with their own verified Supabase account. Household data is available only through membership, and the app lets a member select which of their households is active. Installing the plugin does not grant household access.

## Install in Codex

Add the GitHub marketplace and install Meal Prep:

```bash
codex plugin marketplace add bhadrip/meal-prep --ref main
codex plugin add meal-prep@badri-personal-plugins
```

Start a new Codex chat after installation, open the Meal Prep connector, and sign in with your Supabase account.

To fetch and install a newer version later:

```bash
codex plugin marketplace upgrade badri-personal-plugins
codex plugin add meal-prep@badri-personal-plugins
```

`badri-personal-plugins` resolves through [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json), which points to [`plugin/`](plugin/). A Git marketplace upgrade fetches the latest `main`; a marketplace configured from a local checkout reads that checkout instead, so update it with `git pull origin main` before reinstalling.

## Connect from a chat assistant

Add the remote MCP server `https://meal-prep.madhavan-padmaja.dev/mcp` in a client that supports remote MCP and OAuth. After sign-in, the client discovers the Meal Prep tools. The same household data is available in the [web app](https://meal-prep.madhavan-padmaja.dev/app).

### ChatGPT

1. Enable **Developer mode** in **Settings → Security and login**.
2. In **ChatGPT Plugins**, select **+** and create a connection named **Meal Prep**.
3. Use the MCP URL above.
4. Review the discovered tools and sign in with your Supabase account.
5. Start a new conversation and select **Meal Prep** from the tools menu.

ChatGPT connects to the deployed MCP service; installing or updating the repository package does not deploy server changes. Server and MCP UI changes must also be deployed to Vercel.

### Claude

Open **Customize → Connectors**, add a custom connector, and enter the MCP URL above. Sign in with an approved account. This connection has not yet been tested with Claude.

### Claude Code

Connect directly to production:

```bash
claude mcp add --transport http meal-prep https://meal-prep.madhavan-padmaja.dev/mcp
```

Open `/mcp` in Claude Code to authenticate and inspect the server's discovered
tools, then start a fresh session after a server update. Recipe creation and
editing use `save_recipe`; client-added prefixes vary. With tool search enabled,
ask Claude to search for that exact name before treating a partial visible tool
list as the server's complete inventory. The server marks recipe saving with
`_meta["anthropic/alwaysLoad"]: true`, which supported Claude Code versions use
to keep it available without a search step. Other tools remain discoverable on
demand. The discovery guidance is also at the beginning of the MCP server's
instructions so it survives Claude Code's default 2,048-character truncation.
See [Claude Code's tool search documentation](https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search).

The production endpoint returns the complete tool inventory in one `tools/list`
response, without `nextCursor`. If a tool is still missing, record the version
(`claude --version`), the configured URL, the `/mcp` tool count, and the server's debug
output. Compare the actual discovery response with the client inventory. For a
diagnostic session, `ENABLE_TOOL_SEARCH=false claude` loads definitions upfront;
it cannot repair a client that received an incomplete discovery response.

## Repository

- [`backend/`](backend/) — website, application services, MCP and HTTP transports, Supabase integration and migrations, tests, and Vercel configuration
- [`plugin/`](plugin/) — portable plugin manifest, MCP connection, assets, and planning skill
- [`Meal_Prep_AI_Native_Product_Design.docx`](Meal_Prep_AI_Native_Product_Design.docx) — product and system-design source

See [`backend/README.md`](backend/README.md) for local development, configuration, testing, and deployment.
