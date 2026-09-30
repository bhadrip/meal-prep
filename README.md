# Meal Prep

Meal Prep is a household food-planning app available as a website and a hosted MCP service. It coordinates breakfasts, lunches, dinners, snacks, weekend prep, pantry inventory, and store-prioritized shopping around a family’s actual week.

The website offers direct, manual access to household setup, planning, recipes, pantry, shopping, and feedback. The installable plugin supplies workflow guidance and the MCP connection. Both use the same application services and Supabase household data. The website has no AI features.

```text
Website           → HTTP API ─┐
Codex / ChatGPT   → MCP BFF ──┼→ application services → Supabase
Future mobile app → HTTP API ─┘
```

## Website

Once this change is deployed, open the [Meal Prep website](https://meal-prep-swart.vercel.app/) and sign up or sign in with the same Supabase email used for the MCP connection. Browser and MCP clients have separate sessions, but they share the same identity and household data. The site supports manual edits and never places grocery orders.

For local demo mode or a full local Supabase and email flow, see [`backend/README.md`](backend/README.md#run-locally).

## Access

The hosted service uses a private Supabase project. Before signing in, contact [BhadriP](https://github.com/bhadrip) and include the email address that should be added to Supabase. Installing the plugin does not grant database access.

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

## Connect from ChatGPT

1. Enable **Developer mode** in **Settings → Security and login**.
2. In **ChatGPT Plugins**, select **+** and create a connection named **Meal Prep**.
3. Use `https://meal-prep-swart.vercel.app/mcp` as the MCP URL.
4. Review the discovered tools and sign in with your Supabase account.
5. Start a new conversation and select **Meal Prep** from the tools menu.

ChatGPT connects to the deployed MCP service; installing or updating the repository package does not deploy server changes. Server and MCP UI changes must also be deployed to Vercel.

## Install in Claude

Open **Customize → Plugins → Add marketplace**, enter `bhadrip/meal-prep`, install **Meal Prep**, and connect it from the plugin’s **Connectors** tab. Use **Check for updates** or enable automatic marketplace sync for later releases.

## Repository

- [`backend/`](backend/) — website, application services, MCP and HTTP transports, Supabase integration and migrations, tests, and Vercel configuration
- [`plugin/`](plugin/) — portable plugin manifest, MCP connection, assets, and planning skill
- [`Meal_Prep_AI_Native_Product_Design.docx`](Meal_Prep_AI_Native_Product_Design.docx) — product and system-design source

See [`backend/README.md`](backend/README.md) for local development, configuration, testing, and deployment.
