# Supabase deployment

The Supabase GitHub integration for this repository uses `backend` as its
working directory because this folder contains `supabase/`. It deploys
checked-in migrations to the production project when a pull request is merged
into `main`.

Check the production migration history after each merge. The latest version
should match the newest file in `migrations/` before relying on new database
features in the website or MCP server.
