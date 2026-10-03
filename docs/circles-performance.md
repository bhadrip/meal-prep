# Circles responsiveness

Research and implementation notes, October 3, 2026.

## What the published engineering work supports

Slack's [Making Slack Faster By Being Lazy](https://slack.engineering/making-slack-faster-by-being-lazy/) describes loading the active conversation first, fetching modest pages of history, caching recent conversations, and preparing likely next views. Its [incremental boot](https://slack.engineering/getting-to-slack-faster-with-incremental-boot/) work separates the initial usable interface from secondary data loading. These are historical engineering reports, not a claim about the exact current Slack client.

Slack's [real-time messaging architecture](https://slack.engineering/real-time-messaging/) documents persistent WebSocket connections for receiving events, while sending messages uses its Webapp API. Meta's [WhatsApp multi-device architecture](https://engineering.fb.com/2021/07/14/security/whatsapp-multi-device/) describes companion devices reading synchronized history from their own local databases. The practical lesson for Circles is to keep an immediately usable local view and synchronize it separately from user interaction.

Google's [INP guidance](https://web.dev/articles/optimize-inp) defines good responsiveness as INP at or below 200 ms. Our proposed product targets are feedback on send or cached navigation within 100 ms and field INP at or below 200 ms at the 75th percentile. These are targets, not production measurements or guarantees about server acknowledgement time.

## Implemented in this change

- One layout with a conversation list, bounded message viewport, visible composer, and one temporary detail panel. Members, share selection, review, and threads share the panel; mobile returns to the same conversation and draft.
- Keyed DOM reconciliation preserves message nodes, scroll containers, the live composer, mention instances, focus, cursor selection, and drafts during incoming updates. Unchanged inputs do not get replaced by an entire-page render.
- Up to ten recently visited group feeds are cached in memory. Switching renders that room immediately, then revalidates membership and history. Drafts are separate per circle. Feed caches are cleared on explicit refresh; drafts and pending state are cleared on a household change. Nothing is persisted to disk.
- The active feed request starts alongside the circle list and optional thread detail. Direct shares, public links, and other circle previews load separately and cannot block the conversation.
- Food autocomplete searches existing service endpoints on demand, debounces by 100 ms, limits results to twenty, and keeps at most forty query results in session memory. It does not preload every recipe to open a chat. Search caches are cleared when refreshing household data.
- Plain text sends show a pending message before waiting for the POST. The server's acknowledgement supplies the actual published message; there is no second full reload. Failure removes the pending item and retains the draft. Newer typing is retained when an earlier send succeeds. No automatic resend occurs after an ambiguous network failure.
- Active conversation updates run every three seconds, including while typing. They fetch only the active history and optional open thread. Membership and sharing lists refresh every thirty seconds. Hidden pages pause polling. Request generations discard stale room and household responses.
- Existing service validation, frozen audiences, privacy boundaries, and explicit food/week reviews remain authoritative. These UI optimizations use the same API/application operations as direct MCP clients.

## Next steps for true live delivery

The current implementation is polling, not a persistent event stream. Polling also rereads a bounded page rather than receiving only changed records. Three-second updates improve the existing twelve-second, typing-paused behavior but do not achieve Slack-like instant remote delivery.

A follow-up should add authenticated, membership-scoped server events with reconnect and catch-up support, plus lightweight conversation summaries. Emit invalidation events for messages, replies, revocations, and membership changes; clients refetch through authorized services. Do not subscribe directly to private tables that currently have no client grants. Implement the capability in the backend and expose equivalent incremental reads or subscriptions through MCP as supported by its transport, with API/MCP authorization tests and rendered two-client tests. Start with scoped invalidation rather than duplicating the entire messaging architecture.

Other measured follow-ups: cursor-based history pagination instead of offset drift during concurrent posts; virtualize history when actual DOM or memory profiles justify it; replace background full snapshots with compact room previews; add idempotency keys before automatic retry; collect real interaction, acknowledgement, and remote delivery latency under realistic network and CPU conditions. Account-scoped persistent storage would require a separate privacy and invalidation design; the present session cache is intentionally ephemeral.

## Verification

`ui-tests/circles-performance.spec.js` tests preserved geometry and drafts on desktop/mobile, incoming messages while typing with the same DOM node and cursor selection, cached switching while network requests are held, pending sends and failed-send recovery without duplicate publication, and food requests that cannot block plain messages. Existing Circles and sharing-hub suites verify sharing review, exact thread scope, saved food, mobile navigation, and public/direct sharing.

`backend/tests/test_circles.py` tests that the send acknowledgement contains the complete displayable message, invalid and unauthorized sends leave history unchanged, member management leaves the owner's conversation intact, and removal immediately ends a friend's read access.
