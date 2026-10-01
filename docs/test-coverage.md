# UI and backend test coverage

The Chromium suite exercises every currently visible website form and action. Each test uses the rendered UI and checks the resulting state. The backend suite checks the corresponding HTTP routes; the local Supabase integration test checks the authenticated database path used for weekly plans.

| Surface | UI paths exercised | Backend checks |
| --- | --- | --- |
| Landing and invitations | Landing links and MCP URL copy; signed-out invitation, empty state, account switch, invitation error/retry/accept | Invitation lifecycle and access routes |
| Overview and navigation | One-request startup, saved card order and visibility, sidebar and mobile navigation, shortcuts, sidebar persistence, refresh, account link | Bootstrap and snapshot routes, invitation redirect before household load, household lookup reuse, and health route |
| Weekly plan | Week picker, empty week, day-level Add, top-level Add, rhythm save, meal and prep create/edit/remove, linked recipe, invalid date, same-day meals, switching between saved weeks | Plan and schedule read/write; multiweek demo behavior; authenticated Supabase plan and rhythm roundtrip |
| Recipes | List, search and empty result, detail and back, create/edit/archive, ingredients and method, feedback from detail, share/create/copy/revoke, public page and save | Recipe read/write/archive, detail feedback, lessons, share lifecycle |
| Pantry | List, create, edit, storage, quantity, use-by date; record use for a meal and recipe; remaining amount and visual bar | Pantry read/write and snapshot; use subtraction, recipe link, and overuse rejection through service and HTTP tests |
| Shopping | Store grouping, list rename, item create/edit/remove, purchased and unpurchased states | Shopping list read/write and purchase updates |
| Reviews | Weekly and meal review create/read; memory create/confirm/update/forget | Feedback, what-worked, and memory routes |
| Settings | Household setup, dashboard card order in both directions, visibility on Overview and after reload; invitation create/revoke, member remove, household create/switch/leave | Household, invitation, dashboard, and failed preference write checks |
| Sign-in | Demo screen, code request success/error, email change, invalid/valid code, sign-out | Shared bearer-token validation dependency |
| OAuth consent | Missing request, signed-out redirect, scope display, approval, denial, unsupported callback | OAuth metadata and MCP HTTP tests |
| Embedded MCP App | Dashboard, onboarding, plan, recipes, feedback, shopping, pantry use; empty and unavailable states; shopping progress; recipe search/detail/share/copy/revoke | MCP tool and resource tests, including pantry-use tool discovery |

There is no delete control for pantry items or feedback entries in the current website. The CI browser suite simulates the auth provider and chat host; the Supabase job exercises a real local Auth, PostgREST, and database stack. A live production account and external MCP host are outside CI.
