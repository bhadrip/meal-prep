# Meal Prep

This repository contains a persistent Meal Prep plugin for ChatGPT, its FastAPI/MCP service, the Supabase data model, and the original product-design brief.

- [`meal-prep-mvp/`](meal-prep-mvp/) — dashboard, MCP server, Supabase migrations, tests, and Vercel configuration
- [`meal-prep-plugin/`](meal-prep-plugin/) — portable Agent Plugin manifest and workflow skill
- [`Meal_Prep_AI_Native_Product_Design.docx`](Meal_Prep_AI_Native_Product_Design.docx) — product and system design source

See [`meal-prep-mvp/README.md`](meal-prep-mvp/README.md) for local development and deployment instructions.

## Add to ChatGPT

You do not need Codex or a command-line installation. In ChatGPT:

1. Open **Settings → Security and login** and turn on **Developer mode**.
2. Open **ChatGPT Plugins** and select the **+** button.
3. Name the connection **Meal Prep** and paste this MCP URL:

   ```text
   https://meal-prep-swart.vercel.app/mcp
   ```

4. Create the connection, review its discovered tools, and complete the BhadriP/Supabase login when prompted.
5. Start a new ChatGPT conversation and select **Meal Prep** from the tools or More menu.

The GitHub repository contains the installable package and source, but ChatGPT connects to the live `/mcp` endpoint above.

## Optional GitHub marketplace installation

For ChatGPT desktop development or other compatible local clients, the repository can also be added as a marketplace source:

```bash
codex plugin marketplace add bhadrip/meal-prep --ref main
```

Restart the ChatGPT desktop app, open the Plugins Directory, choose **BhadriP Plugins**, and install **Meal Prep**.

## Add to Claude

Claude can install the full plugin—skill plus remote MCP connector—directly from this GitHub repository:

1. In Claude, open **Customize → Plugins**.
2. Select **Add → Add marketplace**.
3. Enter `bhadrip/meal-prep` or `https://github.com/bhadrip/meal-prep`.
4. Open the new **bhadrip-plugins** marketplace and add **Meal Prep**.
5. Open the plugin's **Connectors** tab and connect the Meal Prep service through OAuth.

For connector-only use, open **Customize → Connectors → Add custom connector** and enter:

```text
https://meal-prep-swart.vercel.app/mcp
```

Marketplace installations receive new plugin versions from GitHub. In Claude, use **Check for updates** or enable **Sync automatically** for this GitHub marketplace.

## MCP UI

The MCP server currently exposes two interactive presentation resources:

- **Weekly meal plan** — a responsive seven-column calendar of saved meals with day/date, meal title, and servings.
- **Shopping list** — store-priority groups with quantities and interactive purchased checkboxes that call `mark_item_purchased` and persist progress.

Both have empty states, adapt to light/dark mode, and remain separate from the underlying structured-data tools.
