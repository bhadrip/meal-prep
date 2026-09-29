# Household invitations: proposed flow

## Goal

Let someone who manages a household invite another adult, such as a spouse, to use the same Meal Prep data from their own account. The invitee must choose to join; receiving an email alone does not grant access.

## Recommended user flow

1. In **Settings → Household members**, the owner sees current members and pending invitations. They enter an email address and select **Invite**. The first version offers one collaborator role: **Adult**, with access to the shared plan, recipes, pantry, shopping list, feedback, and household preferences.
2. Meal Prep emails a private invitation link that names the household and inviter. The owner can see whether it is pending, accepted, expired, or revoked, and can resend or revoke a pending invitation.
3. The invitee opens the link, signs in or creates an account with the **same email address**, and sees the household name and what will be shared. They explicitly select **Join household**.
4. Acceptance adds the invitee as a member of the existing household. Their next website or MCP request uses that household, so both people see and edit the same data. The owner sees them in the member list.
5. The owner can remove a collaborator later. Removal takes effect on the next authenticated request and does not delete household data.

## Product rules for the first version

- Only an owner can invite, revoke invitations, or remove members. An adult can edit shared food data and preferences, but cannot manage membership.
- An invitation is tied to one email address, expires after seven days, and can be accepted once. The app checks the signed-in account's verified email before joining.
- Acceptance is atomic: it consumes the invitation and adds the member together. Revoked, expired, already used, or wrong-email links explain what happened without granting access.
- Keep one active household per account in this version. If an invitee already belongs to a different configured household, show a clear conflict and do not silently switch, merge, or discard data. A brand-new empty household created automatically before acceptance may be replaced after verifying it has no user content.
- Avoid changing `householdSize` automatically. It describes the number of people to plan food for, not the number of app accounts.
- Record who invited, accepted, revoked, or removed someone for support and accountability. Do not display another person's private sign-in details beyond the email needed to manage the invitation.

## Current architecture this builds on

The database already has `household_members` and an `adult` role, with row-level access based on membership. The application currently creates a personal household on first use, chooses the earliest membership as the active household, and the login page only signs in pre-existing accounts. The invitation flow therefore needs account provisioning, an acceptance path before automatic household creation, and a clear rule for existing households. These are part of this feature, not just a new settings form.

## Suggested delivery order

1. Add invitation storage and server-side operations for create, list, revoke, accept, and member removal. Keep membership changes behind owner and invitee checks in the database.
2. Add the household member section in website Settings and an invitation landing page that works before the normal household snapshot loads.
3. Add invite-only account creation and email delivery, then verify the full path with a second account through website and MCP.

## Decisions to settle before implementation

1. Should invited adults have the same editing access as the owner, with membership management reserved for the owner? **Recommendation: yes.**
2. If your wife has already created a separate household with data, should the first version block joining until we provide an explicit migration or switching flow? **Recommendation: yes.**
3. Should the first release include only email invitations, or also a copyable link? **Recommendation: email only, because the invitation is bound to the recipient's email anyway.**
