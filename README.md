# Meal Prep

This repository contains a persistent Meal Prep plugin for ChatGPT and Codex, its FastAPI/MCP service, the Supabase data model, and the original product-design brief.

- [`meal-prep-mvp/`](meal-prep-mvp/) — dashboard, MCP server, Supabase migrations, tests, and Vercel configuration
- [`meal-prep-plugin/`](meal-prep-plugin/) — portable Agent Plugin manifest and workflow skill
- [`Meal_Prep_AI_Native_Product_Design.docx`](Meal_Prep_AI_Native_Product_Design.docx) — product and system design source

See [`meal-prep-mvp/README.md`](meal-prep-mvp/README.md) for local development and deployment instructions.

## Add the plugin from GitHub

Add this repository as a plugin marketplace source:

```bash
codex plugin marketplace add bhadrip/meal-prep --ref main
```

Restart the ChatGPT desktop app, open the Plugins Directory, choose **Badri P. Plugins**, and install **Meal Prep**.

For a direct ChatGPT developer-mode connection, use the deployed MCP endpoint:

```text
https://meal-prep-swart.vercel.app/mcp
```

## MCP UI

The MCP server currently exposes two interactive presentation resources:

- **Weekly meal plan** — a responsive seven-column calendar of saved meals with day/date, meal title, and servings.
- **Shopping list** — store-priority groups with quantities and interactive purchased checkboxes that call `mark_item_purchased` and persist progress.

Both have empty states, adapt to light/dark mode, and remain separate from the underlying structured-data tools so the plugin also works headlessly in Codex.
