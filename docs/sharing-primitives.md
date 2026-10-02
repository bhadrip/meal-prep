# Public recipe link sharing

This document records the public recipe-link model. Private friend-circle sharing of weekly plans and recipes is implemented separately in [Friend circles](friend-circles.md).

Meal Prep stores recipes under a household and currently returns private cooking feedback with a recipe detail. Sharing needs its own explicit payload and access path; a recipient must not inherit household access.

## Model

1. **Artifact:** a versioned, allowlisted snapshot of one item. The first type is `recipe`; a later `achievement` type can use the same sharing path once achievements have a source model. A recipe snapshot contains title, description, servings, times, tags, ingredients, instructions, and source attribution. It excludes household IDs, preferences, pantry, plans, shopping lists, and cooking feedback.
2. **Grant:** the creator chooses an audience and can revoke the grant. A link grant uses an unguessable token. Its public URL reveals only the snapshot, with no access to the original recipe or household. Private circle membership now provides a separate audience model.
3. **Presentation:** the link renders a compact preview and a full recipe page. Social previews and a shareable image can be derived from the snapshot without changing the grant model.
4. **Receipt:** a signed-in recipient can save a recipe as a new recipe in their own household, retaining source attribution. The copy is independent of later edits to the original. Viewing a link does not add anything to the recipient's library.

## First release

- Create a share from a household recipe, show its URL, list link metadata, and revoke a share. The raw URL is returned only when created; it cannot be retrieved later.
- Let anyone holding an active link view the recipe snapshot. Expiration is optional; by default the link remains active until revoked.
- Let an authenticated recipient copy the shared recipe into their own household.
- Keep all sharing opt-in. Archiving or editing the original does not silently change an already published snapshot; revocation removes access to it.
- Do not expose email lookup, a follower graph, public household profiles, or arbitrary private records through this release.

## Decisions and next item types

- Public recipe links use revocable tokens; private friend circles use accepted membership and their own snapshot records.
- A received recipe is an independent copy. The source share ID is retained as provenance, not as an edit link.
- Achievements need a source model before they can be shared as app-verified facts. An achievement snapshot can use the same grant and presentation path, with its own allowlist and card renderer.
- Candidate achievements to discuss: meals planned, recipes tried, pantry items used before expiry, or a weekly prep streak. The event definition, time window, and whether users can edit the wording determine what the card can truthfully claim.

Authorization is enforced in the database. Public reads require the link token and return the allowlisted snapshot only. A token is random and hashed at rest. The public page uses noindex and no-referrer headers; revocation and expiration are checked on every read and copy.
