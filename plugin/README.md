# Meal Prep

Meal Prep combines a reusable planning skill with a remote MCP connector. ChatGPT loads household context, dietary restrictions, preferred stores, weekly schedules, feedback, confirmed household preferences, saved recipes, reusable meals, and pantry data before coordinating breakfasts, lunches, dinners, snacks, prep, and shopping. Feedback connects the recipe or variant, the actual meal occurrence, its week, reusable themes and audiences, and an actionable next-time adjustment. A weekly check-in creates ordinary feedback entries; repeated patterns become household preferences only after confirmation. The remote service persists approved meal plans and shopping lists in Supabase, stores compact pantry photo evidence in a private Storage bucket, and can render MCP-served household onboarding, a chat-configured card dashboard, a pantry photo review gallery, feedback, a shared recipe library with searchable Recipes, Ready food, and Meals type filters, an interactive weekly calendar, or a store-grouped checklist directly in chat. Saving a list never places an order.

After installing the plugin, open its **Connectors** tab and connect the Meal Prep service. Authentication is handled by the service's OAuth flow.

## Package layout

This directory is the single installable package. The repository's
`../.agents/plugins/marketplace.json` is its catalog entry, not another plugin.
It points to `./plugin` relative to the repository root.

- `plugin.json` owns identity, version, homepage, and OpenAI presentation under
  `extensions.com.openai`.
- `mcp.json` owns the remote MCP connection at
  `https://meal-prep.madhavan-padmaja.dev/mcp` using `streamable-http`.
- `skills/` contains the planning workflow; `assets/` contains package icons.

This uses the [portable Agent Plugins format](https://developers.openai.com/plugins/build/plugins).
Skills and MCP configuration are discovered at these fixed paths. Do not add
copies under `.codex-plugin/`, `.claude-plugin/`, or `.mcp.json`; the portable
manifest already includes OpenAI settings. The former repository-level Claude
catalog pointed at the nonexistent `meal-prep-plugin` folder and has been removed.
Claude users can still connect directly to the remote MCP URL as described in
the repository README; a Claude Code plugin package is not maintained here.

When changing the public domain, update this package's endpoint and homepage
along with the server's `APP_BASE_URL`. OAuth metadata must advertise the exact
MCP URL clients use. Increment `plugin.json`'s version for installable changes;
existing cached installations need a marketplace upgrade and reinstall, then a
new chat to load the updated tools. Refresh the connector authorization if prompted.
