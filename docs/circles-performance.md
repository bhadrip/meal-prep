# Chat layout and delivery

The website uses a conversation list, chronological message viewport, persistent composer, and one panel for threads, members, food selection or review. Desktop panels sit beside the timeline; phones show one pane at a time. The layout follows the visible viewport when a keyboard opens.

## Interaction and state

Keyed DOM reconciliation retains message nodes, timeline scroll position, composer identity, drafts, mention instances, focus and selection during updates. Ten recently visited feeds are cached in memory and revalidated on opening. Drafts stay scoped to a conversation; household changes clear chat state. These caches are ephemeral and contain no disk persistence.

Text sends clear the composer immediately and show a pending bubble. Failures keep the bubble with explicit retry/edit actions. Retries use the original UUID and identical payload; database locking prevents concurrent retries from publishing twice. Retrying an earlier failed message preserves a newer composer draft. Food and week sends still review their snapshot and audience before publication.

Room lists contain compact latest-message titles/captions, unread counts, names and mute state. Full snapshots load only in the conversation or thread. Food searches run on demand; they have loading, empty and failure states. Search runs against authorized history, not just the loaded viewport, and supports sender, date and type filters with cursor continuation.

History starts with 50 posts. Cursor pages use creation time and UUID, so incoming posts do not shift an offset boundary. Loading older messages anchors the current reading position. Incoming messages scroll only when the reader is already at the bottom; otherwise a Jump to latest action appears. Read positions move forward only. Display names, quotes, text edits, reactions and read counts use the same services for HTTP and MCP.

## Live delivery

`/api/chat-events` is an authenticated, bounded SSE stream. It emits caller-scoped version invalidations, without private message bodies. A database trigger increments durable user versions for messages, replies, revocations, membership changes, profiles, reactions and read/mute state. The stream checks that lightweight version each second and expires after 20 seconds; reconnect validates the session again. This supports the existing serverless hosting model without opening private table access.

The client reconnects with exponential backoff, catches up from the durable version, stops while hidden or outside Chats, and restarts on connectivity or visibility changes. It refetches authorized conversation/history data when notified. The old three-second history polling and thirty-second full-list loops are removed. Direct MCP clients use `get_chat_sync` with the same scoped versions and the conversation/history tools.

This delivers near-live invalidation, with up to the version check interval plus network latency. It is not a websocket or a claim of measured production delivery latency. Very large loaded histories are not virtualized; add virtualization after profiling real conversation sizes. Initial histories and room previews remain bounded.

## Persistence and privacy

Apply `backend/supabase/migrations/202610050001_chat_revamp.sql` after the existing migrations. It adds profiles, read/mute states, reactions, idempotent sends, versions and authorization RPCs. New private tables have RLS and no direct authenticated/anonymous grants. Existing MCP tools, food snapshots, notifications and publication reviews stay supported.

Repeated direct shares reuse the earliest accepted two-person room. Legacy rooms are consolidated for display without rewriting posts or recipients. Every history result, quote, action, reaction and read position verifies the original post's captured membership epoch. Removing and re-inviting someone cannot restore old content or reactions. Muting suppresses future in-app chat notifications; it does not revoke membership.

## Verification

`ui-tests/chat-revamp.spec.js` covers quotes, reactions, editing and failed edit recovery, real server search and filters, mute/profile persistence, invitation failures, picker retry/removable attachments, cursor scroll anchoring, Jump to latest, persistent direct conversations, two-tab delivery/reconnect, mobile keyboard height, week navigation and pantry filter reset.

`ui-tests/circles-performance.spec.js`, `ui-tests/circles.spec.js` and `ui-tests/sharing-hub.spec.js` cover composer identity, request races, retries, recipient review, frozen snapshots, exact threads and mobile return navigation. The full Playwright suite also checks the wider website and embedded MCP App in Chromium, Android and iPhone profiles.

`backend/tests/test_chat_revamp.py`, `backend/tests/test_mcp.py` and `backend/tests/test_supabase_integration.py` verify shared service/transport behavior, invalid inputs, idempotency conflicts and concurrency, history cursors, author/member boundaries, legacy room consolidation, frozen audiences, unread/read state, notification muting and real database persistence.
