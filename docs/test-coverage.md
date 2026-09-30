# UI and backend test coverage

The Chromium suite exercises every currently visible website form and action. Each test uses the rendered UI and checks the resulting state. The backend suite checks the corresponding HTTP routes; the local Supabase integration test checks the authenticated database path used for weekly plans.

| Surface | UI paths exercised | Backend checks |
| --- | --- | --- |
| Overview and navigation | Sidebar and mobile navigation, shortcuts, sidebar persistence, refresh, account link | Snapshot and health routes |
| Weekly plan | Week picker, empty week, day-level Add, top-level Add, rhythm save, meal and prep create/edit/remove, linked recipe, invalid date, same-day meals, switching between saved weeks | Plan and schedule read/write; multiweek demo behavior; authenticated Supabase plan and rhythm roundtrip |
| Recipes | List, search and empty result, detail and back, create/edit/archive, ingredients and method, feedback from detail, share/create/copy/revoke, public page and save | Recipe read/write/archive, detail feedback, lessons, share lifecycle |
| Pantry | List, create, edit, storage, quantity, use-by date | Pantry read/write and snapshot |
| Shopping | Store grouping, list rename, item create/edit/remove, purchased and unpurchased states | Shopping list read/write and purchase updates |
| Reviews | Feedback create/read; memory create/confirm/update/forget | Feedback, what-worked, and memory routes |
| Settings | Household setup, dashboard card order in both directions, visibility, saved values after reload | Household and dashboard read/write/reset |
| Sign-in | Demo screen, code request success/error, email change, invalid/valid code, sign-out | Shared bearer-token validation dependency |
| OAuth consent | Missing request, signed-out redirect, scope display, approval, denial, unsupported callback | OAuth metadata and MCP HTTP tests |
| Embedded MCP App | Dashboard, onboarding, plan, recipes, feedback, shopping; empty and unavailable states; shopping progress; recipe search/detail/share/copy/revoke | MCP tool and resource tests |

There is no delete control for pantry items or feedback entries in the current website. The CI browser suite simulates the auth provider and chat host; the Supabase job exercises a real local Auth, PostgREST, and database stack. A live production account and external MCP host are outside CI.
