# Sharing primitives (proposal)

Meal Prep stores recipes under a household and currently returns private cooking feedback with a recipe detail. Sharing needs its own explicit payload and access path; a recipient must not inherit household access.

## Model

1. **Artifact:** a versioned, allowlisted snapshot of one item. The first type is `recipe`; a later `achievement` type can use the same sharing path once achievements have a source model. A recipe snapshot contains title, description, servings, times, tags, ingredients, instructions, and source attribution. It excludes household IDs, preferences, pantry, plans, shopping lists, and cooking feedback.
2. **Grant:** the creator chooses an audience and can revoke the grant. A link grant uses an unguessable token. Its public URL reveals only the snapshot, with no access to the original recipe or household. A future named-user grant can point to the same artifact model.
3. **Presentation:** the link renders a compact preview and a full recipe page. Social previews and a shareable image can be derived from the snapshot without changing the grant model.
4. **Receipt:** a signed-in recipient can save a recipe as a new recipe in their own household, retaining source attribution. The copy is independent of later edits to the original. Viewing a link does not add anything to the recipient's library.

## Proposed first release

- Create a share from a household recipe, show its URL, list active shares, and revoke a share.
- Let anyone holding an active link view the recipe snapshot. Support an optional expiration time.
- Let an authenticated recipient copy the shared recipe into their own household.
- Keep all sharing opt-in. Archiving or editing the original does not silently change an already published snapshot; revocation removes access to it.
- Do not expose email lookup, a follower graph, public household profiles, or arbitrary private records through this release.

## Open decisions

- Should the first release use revocable links, named recipients, or both?
- Should a received recipe be an independent copy or a live reference?
- Should a share expire by default, or remain active until revoked?
- Which event should count as a Meal Prep achievement, and should it be app-verified or user-authored?

The implementation should enforce authorization in the database, not only in the MCP or HTTP layer. Public reads should require the link token and return the allowlisted snapshot only. Tests should cover another household's inability to read or modify the source and the behavior of revoked or expired links.
