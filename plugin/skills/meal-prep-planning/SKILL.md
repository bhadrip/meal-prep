---
name: meal-prep-planning
description: Coordinate the household food week and open or configure its card dashboard with the Meal Prep MCP tools. Use for meal planning, recipes, recipe sharing, prep, pantry inventory, shopping lists, household food preferences, or dashboard requests.
---

# Meal prep planning

Connect to the Meal Prep MCP server and follow its initialization instructions.
The server owns the complete planning, dashboard, feedback, pantry, and recipe
sharing workflow so direct MCP clients receive the same guidance as this plugin.
Use `get_planning_context` before drafting or revising a weekly plan, and select
the intended household before reading or changing its data.

Use the server's MCP App views when supported. Otherwise present the structured
tool results in chat and collect required household setup answers conversationally.
The plugin provides discovery, connection configuration, and starter prompts;
backend/app/transports/meal-prep-instructions.md is the workflow source of truth
in the repository, not a file clients need to access.
