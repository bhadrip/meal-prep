# Friend circles

Circles are small, private groups for sharing food plans with friends. A person creates a circle and invites existing Meal Prep accounts. Invitees see an in-app notification and can accept or decline. The owner can remove a member; members can leave. Only accepted members can read the feed or comment. Leaving or removal immediately ends access to posts and circle notifications. Saved recipe copies remain in the recipient's own household.

The Circle tab shows a concise wall of two post types:

- **Weekly plan:** one explicit, immutable snapshot of the whole week. It includes every planned meal slot, meal notes and components, plus the full saved recipe or ready food details referenced by those meals. A repeated recipe appears once in the snapshot. Pantry IDs and stock quantities, prep tasks, shopping data, household preferences, and unrelated recipes are excluded. Changing the source plan or recipe later does not alter the post; the author can share the week again to publish an update.
- **Recipe or ready food:** one explicit, immutable snapshot of that library item.

Members can comment on a whole post, a meal in a week, or a recipe included in the post. They cannot edit the source household's plan or library. A member can save one shared recipe into their active household. That creates an independent recipe with source attribution; later shares of the same source show the existing household copy. Archiving the copy permits a fresh save. There is no whole-plan copy action. A post's author can revoke it, which ends access to its snapshot and discussion.

The database builds snapshots from the author's active household inside authorized RPC functions. The circle tables have no direct client grants. Feed reads, detail reads, comments, and saves check accepted circle membership. New posts and comments use the existing in-app notification inbox; no email or push path is involved. The website refreshes notifications on opening the inbox, window focus, and while visible.

Direct MCP clients have the same circle actions as the website. `list_shared_with_me` accepts `kind`, `limit`, and `offset`; follow `nextOffset` until it is `null` to inspect all visible weeks and recipes for planning inspiration. `get_shared_item` returns the snapshot and discussion. The server's planning instructions describe how to use shared food as inspiration without copying a whole friend's plan. Sharing and saving are deterministic application operations; no AI is called by the feature.

The later “hide this meal” idea is not part of this first version. Until then, the author should treat sharing a week as publishing every planned meal in it to every accepted member of the selected circle.
