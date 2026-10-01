# Meal Prep

Meal Prep is a household food-planning app available as a website and a hosted MCP service. It coordinates breakfasts, lunches, dinners, snacks, weekend prep, pantry inventory, and store-prioritized shopping around a family’s actual week.

The website offers direct, manual access to household setup, planning, recipes, pantry, shopping, and feedback. The installable plugin supplies workflow guidance and the MCP connection. Both use the same application services and Supabase household data. The website has no AI features.

The website also has a personal notification inbox for household invitations and activity. Alerts stay in the website; they do not send email or push messages. The inbox shows activity from households you still belong to, and opening an alert switches to its household when needed.

```text
Website           → HTTP API ─┐
Codex / ChatGPT   → MCP BFF ──┼→ application services → Supabase
Future mobile app → HTTP API ─┘
```

## Website

Open the [Meal Prep landing page](https://meal-prep-swart.vercel.app/) and choose **Open the app**, or go straight to `/app`. Sign up or sign in with the same Supabase email used for the MCP connection. Browser and MCP clients have separate sessions, but they share the same identity and active household. The app supports manual edits and never places grocery orders.

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

Add the remote MCP server `https://meal-prep-swart.vercel.app/mcp` in a client that supports remote MCP and OAuth. After sign-in, the client discovers the Meal Prep tools. The same household data is available in the [web app](https://meal-prep-swart.vercel.app/app).

### ChatGPT

1. Enable **Developer mode** in **Settings → Security and login**.
2. In **ChatGPT Plugins**, select **+** and create a connection named **Meal Prep**.
3. Use the MCP URL above.
4. Review the discovered tools and sign in with your Supabase account.
5. Start a new conversation and select **Meal Prep** from the tools menu.

ChatGPT connects to the deployed MCP service; installing or updating the repository package does not deploy server changes. Server and MCP UI changes must also be deployed to Vercel.

### Claude

Open **Customize → Connectors**, add a custom connector, and enter the MCP URL above. Sign in with an approved account. This connection has not yet been tested with Claude.

## Repository

- [`backend/`](backend/) — website, application services, MCP and HTTP transports, Supabase integration and migrations, tests, and Vercel configuration
- [`plugin/`](plugin/) — portable plugin manifest, MCP connection, assets, and planning skill
- [`Meal_Prep_AI_Native_Product_Design.docx`](Meal_Prep_AI_Native_Product_Design.docx) — product and system-design source

See [`backend/README.md`](backend/README.md) for local development, configuration, testing, and deployment.
