"""Chat persistence adapters. No UI-specific behavior or authorization bypasses."""
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
from ..application.errors import RepositoryError


class SupabaseChat:
    async def chat_rooms(self):
        return await self.rpc('chat_rooms')

    async def chat_history(self, circle_id, limit, cursor, query, sender, date_from, kind):
        return await self.rpc('chat_history', {'requested_circle_id': circle_id, 'result_limit': limit,
            'before_cursor': cursor, 'search_text': query, 'sender_id': sender, 'since_date': date_from, 'post_kind': kind})

    async def chat_action(self, action, target, payload):
        return await self.rpc('chat_action', {'requested_action': action, 'requested_target': target, 'payload': payload})

    async def chat_profile(self, name=None):
        return await self.rpc('chat_profile', {'requested_name': name})

    async def chat_sync(self):
        return await self.rpc('chat_sync')

    async def chat_send(self, circle_id, body, kind, attachment, mentions, audience, client_id, reply_to):
        return await self.rpc('chat_send', {'requested_circle_id': circle_id, 'requested_body': body,
            'requested_attachment_kind': kind, 'requested_attachment_id': attachment,
            'requested_mention_ids': mentions, 'requested_audience': audience,
            'client_id': client_id, 'reply_to': reply_to})


class DemoChat:
    def _chat_root(self, room_id):
        room = self._circles[room_id]
        if room.get('roomType') != 'direct': return room_id
        peers = set(room['members'])
        return next((r['id'] for r in self._circles.values() if r.get('roomType') == 'direct'
            and set(r['members']) == peers and all(status == 'accepted' for status in r['members'].values())), room_id)

    def _chat_name(self, user):
        return self._chat['profiles'].get(user, user.split('@')[0])

    def _chat_enrich(self, row):
        result = deepcopy(row)
        result['conversationId'] = self._chat_root(row['circleId'])
        result['createdByName'] = self._chat_name(row['createdBy'])
        result['editedAt'] = self._circle_posts[row['id']].get('editedAt')
        reactions = self._chat['reactions'].get(row['id'], {})
        visible_users={user for user,epoch in self._circle_posts[row['id']]['recipientIds'].items() if self._circles[row['circleId']]['members'].get(user)=='accepted' and self._circles[row['circleId']]['memberEpochs'].get(user)==epoch}
        reactions={emoji:users & visible_users for emoji,users in reactions.items()}
        result['reactions'] = [{'emoji': emoji, 'count': len(users), 'mine': self.user_id in users}
                               for emoji, users in reactions.items() if users]
        result['seenBy'] = sum(user != row['createdBy'] and self._chat['states'].get((user, self._chat_root(row['circleId'])), {}).get('lastReadAt', '') >= row['createdAt']
            for user in self._circle_posts[row['id']]['recipientIds']
            if self._circles[row['circleId']]['members'].get(user) == 'accepted'
            and self._circle_posts[row['id']]['recipientIds'][user] == self._circles[row['circleId']]['memberEpochs'].get(user))
        return result

    async def chat_history(self, circle_id, limit=51, cursor=None, query='', sender=None, date_from=None, kind=None):
        self._circle_access(circle_id)
        rows = [row for row in await self.circle_feed(100000, 0, kind) if self._chat_root(row['circleId']) == self._chat_root(circle_id)]
        rows.sort(key=lambda row: (row['createdAt'], row['id']), reverse=True)
        if cursor:
            stamp, post_id = cursor.rsplit('|', 1)
            rows = [row for row in rows if (row['createdAt'], row['id']) < (stamp, post_id)]
        return [self._chat_enrich(row) for row in rows if
            (not query or query.lower() in (json.dumps(row['snapshot'], ensure_ascii=False) + ' ' +
                ' '.join(c['body'] for c in self._circle_comments.get(row['id'], []) if not c.get('deletedAt'))).lower())
            and (not sender or row['createdBy'] == sender)
            and (not date_from or row['createdAt'][:10] >= date_from)][:limit]

    async def chat_rooms(self):
        groups = {row['id']: row for row in await self.circle_list()}
        result = []
        for room in self._circles.values():
            if room['members'].get(self.user_id) != 'accepted' or self._chat_root(room['id']) != room['id']: continue
            history = await self.chat_history(room['id'], 1)
            latest = history[0] if history else None
            if latest:
                snapshot=latest['snapshot']
                latest['snapshot']={key:snapshot[key] for key in ('text','caption','weekStart') if key in snapshot}
                if 'recipe' in snapshot: latest['snapshot']['recipe']={'title':snapshot['recipe']['title']}
                if 'meal' in snapshot: latest['snapshot']['meal']={'name':snapshot['meal']['name']}
            state = self._chat['states'].get((self.user_id, room['id']), {})
            direct = room.get('roomType') == 'direct'
            peer = next((u for u in room['members'] if u != self.user_id), '')
            unread = sum(row['createdBy'] != self.user_id and row['createdAt'] > state.get('lastReadAt', '')
                         for row in await self.chat_history(room['id'], 100000))
            result.append({**groups.get(room['id'], {}), 'id': room['id'], 'name': self._chat_name(peer) if direct else room['name'],
                'roomType': 'direct' if direct else 'group', 'ownerId': room['ownerId'], 'myStatus': 'accepted',
                'memberCount': sum(v == 'accepted' for v in room['members'].values()),
                'members': [{'userId': u, 'email': u, 'status': status, 'name': self._chat_name(u)} for u, status in room['members'].items()],
                'audience': [{'userId': u, 'membershipId': room['memberEpochs'][u], 'name': self._chat_name(u)} for u,status in room['members'].items() if status=='accepted'],
                'memberNames': [self._chat_name(u) for u,status in room['members'].items() if status=='accepted'],
                'latest': latest, 'unreadCount': unread, 'muted': state.get('muted', False),
                'lastReadId': state.get('lastReadId'), 'lastReadAt': state.get('lastReadAt')})
        return sorted(result, key=lambda room: (room['latest'] or {}).get('createdAt', ''), reverse=True)

    async def chat_send(self, circle_id, body, kind, attachment, mentions, audience, client_id, reply_to):
        self._circle_access(circle_id)
        signature = json.dumps([circle_id, body, kind, attachment, mentions, audience, reply_to], sort_keys=True)
        key = (self.user_id, client_id)
        previous = self._chat['sends'].get(key) if client_id else None
        if previous:
            if previous['signature'] != signature: raise RepositoryError('Retry content changed; use a new send identifier')
            await self.circle_get_post(previous['id'])
            return self._chat_enrich(self._circle_summary(self._circle_posts[previous['id']]))
        quoted = None
        if reply_to:
            quoted = await self.circle_get_post(reply_to)
            if quoted['conversationId'] != self._chat_root(circle_id): raise RepositoryError('Reply belongs to another conversation')
        sent = await self.circle_send_message(circle_id, body, kind, attachment, mentions, audience)
        if quoted:
            self._circle_posts[sent['id']]['snapshot']['replyTo'] = {'id': quoted['id'], 'name': quoted['createdByName'],
                'text': (quoted['snapshot'].get('text') or quoted['snapshot'].get('caption') or quoted['kind'])[:160]}
        if client_id: self._chat['sends'][key] = {'signature': signature, 'id': sent['id']}
        return self._chat_enrich(self._circle_summary(self._circle_posts[sent['id']]))

    async def chat_action(self, action, target, payload):
        if action == 'state':
            self._circle_access(target)
            target=self._chat_root(target)
            state = self._chat['states'].setdefault((self.user_id, target), {})
            if payload.get('lastReadId'):
                post = await self.circle_get_post(payload['lastReadId'])
                if post['conversationId'] != self._chat_root(target): raise RepositoryError('Read position belongs to another conversation')
                if post['createdAt'] >= state.get('lastReadAt', ''):
                    state.update(lastReadId=post['id'], lastReadAt=post['createdAt'])
            if payload.get('muted') is not None: state['muted'] = payload['muted']
            return deepcopy(state)
        post = await self.circle_get_post(target)
        if action == 'edit':
            if post['createdBy'] != self.user_id or post['kind'] != 'message':
                raise RepositoryError('Only your text messages can be edited')
            self._circle_posts[target]['snapshot']['text'] = payload['body']
            self._circle_posts[target]['editedAt'] = datetime.now(UTC).isoformat()
        elif action == 'reaction':
            users = self._chat['reactions'].setdefault(target, {}).setdefault(payload['emoji'], set())
            if payload['active']: users.add(self.user_id)
            else: users.discard(self.user_id)
        else: raise RepositoryError('Unsupported chat action')
        return await self.circle_get_post(target)

    async def chat_profile(self, name=None):
        if name is not None: self._chat['profiles'][self.user_id] = name
        return {'userId': self.user_id, 'name': self._chat_name(self.user_id)}

    async def chat_sync(self):
        # Include membership, thread edits/deletions, reactions and preferences,
        # not only the newest message. This is the deterministic demo adapter.
        rooms = await self.chat_rooms()
        visible = [await self.circle_get_post(row['id']) for row in await self.circle_feed(100000, 0)]
        signature = json.dumps([rooms, visible, await self.circle_list()], sort_keys=True, default=str)
        return {'version': sha256(signature.encode()).hexdigest()}
