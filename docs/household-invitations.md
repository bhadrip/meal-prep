# Household sharing

## User flow

1. Both adults sign up for their own Meal Prep accounts and verify their email addresses.
2. The household owner opens **Settings → Household members** and enters the other person's account email. Meal Prep creates a pending invitation for that verified account. It sends no invitation email.
3. The invitee signs in, sees the pending invitation in Meal Prep, reviews the household name, and selects **Join household**.
4. Both accounts then see and edit the same plan, recipes, pantry, shopping list, feedback, and household preferences on the website and through MCP. The owner can revoke a pending invitation or remove a member later.

## Access rules

- Only an owner can invite, revoke invitations, or remove members. A collaborator has the `adult` role and can edit shared food data and preferences.
- An invitation is bound to a verified account email, expires after seven days, and can be accepted once. A database function checks the signed-in account's verified email before granting membership.
- Acceptance consumes the invitation and adds the member in one transaction. Revoked, expired, used, and wrong-account invitations cannot grant access.
- Each account has one active household. If the invitee already has an untouched empty household created by bootstrap, acceptance replaces it. A configured household or one with food data blocks acceptance, so no data is silently merged or discarded.
- Household size describes the number of people to plan food for and does not change automatically when an account joins.
- Removing a member revokes their membership immediately and revokes recipe sharing links they created for that household. Shared food data stays in the household.

## Implementation

The API uses the caller's Supabase access token. Database functions check the owner role for invitation and removal actions, and row level security gates all shared tables by household membership. The application server has no Supabase secret key for sharing. Sign-up and sign-in still use Supabase Auth magic links, which require email delivery independently of household sharing.
