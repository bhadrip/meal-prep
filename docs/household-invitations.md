# Household sharing

## User flow

1. Both adults sign up for their own Meal Prep accounts and verify their email addresses.
2. The household owner opens **Settings → Household members** and enters the other person's account email. Meal Prep creates a pending invitation for that verified account. It sends no invitation email.
3. The invitee signs in, sees the pending invitation in Meal Prep, reviews the household name, and selects **Join household**.
4. The invited household becomes active. Both accounts can see and edit its plan, recipes, pantry, shopping list, feedback, and preferences on the website and through MCP. The invitee's other households and data remain available from the switcher. The owner can revoke a pending invitation or remove a member later.
5. An account can create additional households from Settings or through MCP. The website switcher and MCP household tools select the active household for subsequent work.

## Access rules

- Only an owner can invite, revoke invitations, or remove members. A collaborator has the `adult` role and can edit shared food data and preferences.
- An invitation is bound to a verified account email, expires after seven days, and can be accepted once. A database function checks the signed-in account's verified email before granting membership.
- Acceptance consumes the invitation and adds the member in one transaction. Revoked, expired, used, and wrong-account invitations cannot grant access.
- Each account can belong to several households and has one active household. Accepting an invitation keeps existing households and selects the newly joined one. Switching changes what the website and MCP tools read and write. Data is never merged between households.
- Household size describes the number of people to plan food for and does not change automatically when an account joins.
- Removing a member revokes their membership immediately and revokes recipe sharing links they created for that household. Shared food data stays in the household. If the removed household was active, the account falls back to another membership.

## Implementation

The API uses the caller's Supabase access token. A private selection row stores the active household and can be changed only by a checked function that confirms membership. Database functions check the owner role in the active household for invitation and removal actions. Row level security scopes tables to the active membership, including direct record requests. The application server has no Supabase secret key for sharing. Sign-up and sign-in use Supabase Auth email codes, which require email delivery independently of household sharing.
