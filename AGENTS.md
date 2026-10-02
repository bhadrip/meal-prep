# Repository instructions

## MCP first

Implement capabilities and shared workflow guidance through the MCP server whenever MCP can support them. Direct MCP clients must receive the same supported behavior without installing the plugin.

Use plugin skills only for capabilities that require plugin-specific features and cannot be supported through MCP. Document the concrete MCP limitation before choosing a plugin-only implementation. Keep shared workflow instructions in the server; plugin skills may provide a thin entry point without duplicating those instructions.

## Feature tests

For every new feature or behavior change, add or extend both:

1. A backend test in `backend/tests/` that verifies the service, API, or MCP behavior and a meaningful failure case.
2. A Playwright test in `ui-tests/` that uses the rendered website or MCP App and verifies the user's action and resulting state.

Assert behavior, not just the presence of text, controls, or tool names. Update `docs/test-coverage.md` with the paths covered. Run the relevant backend and Playwright tests before considering the feature complete.
