# Household invitations

## Goal

Let someone who manages a household invite another adult, such as a spouse, to use the same Meal Prep data from their own account. The invitee must choose to join; receiving an email alone does not grant access.

## Recommended user flow

1. In **Settings → Household members**, the owner sees current members and pending invitations. They enter an email address and select **Invite**. The first version offers one collaborator role: **Adult**, with access to the shared plan, recipes, pantry, shopping list, feedback, and household preferences.
2. Supabase Auth emails a sign-in or account invitation link that leads to Meal Prep's invitation page. The page names the household. The owner can see pending invitations, resend one by entering the same email, or revoke it.
3. The invitee opens the link, signs in or creates an account with the **same email address**, and sees the household name and what will be shared. They explicitly select **Join household**.
4. Acceptance adds the invitee as a member of the existing household. Their next website or MCP request uses that household, so both people see and edit the same data. The owner sees them in the member list.
5. The owner can remove a collaborator later. Removal takes effect on the next authenticated request, revokes recipe sharing links they created for the household, and does not delete household food data.

## Product rules for the first version

- Only an owner can invite, revoke invitations, or remove members. An adult can edit shared food data and preferences, but cannot manage membership.
- An invitation is tied to one email address, expires after seven days, and can be accepted once. The app checks the signed-in account's verified email before joining.
- Acceptance is atomic: it consumes the invitation and adds the member together. Revoked, expired, already used, or wrong-email links explain what happened without granting access.
- Keep one active household per account in this version. If an invitee already belongs to a different configured household, show a clear conflict and do not silently switch, merge, or discard data. A brand-new empty household created automatically before acceptance may be replaced after verifying it has no user content.
- Avoid changing `householdSize` automatically. It describes the number of people to plan food for, not the number of app accounts.
- Record who invited, accepted, revoked, or removed someone for support and accountability. Do not display another person's private sign-in details beyond the email needed to manage the invitation.

## Current architecture this builds on

The database already has `household_members` and an `adult` role, with row-level access based on membership. The application currently creates a personal household on first use, chooses the earliest membership as the active household, and the login page only signs in pre-existing accounts. The invitation flow therefore needs account provisioning, an acceptance path before automatic household creation, and a clear rule for existing households. These are part of this feature, not just a new settings form.

## Implementation

The first release uses email delivery and one shared `adult` role. Owner-only database functions create, revoke, and remove access. The invitee must authenticate with the matching verified email, then accept. The invitation record lasts seven days; Supabase Auth email links may expire sooner and can be resent. Production needs a server-only Supabase secret key, an allowed `/invite` redirect, and custom SMTP for normal external email delivery.
