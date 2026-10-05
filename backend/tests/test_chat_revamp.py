from uuid import uuid4
from copy import deepcopy
import pytest
from app.application.circles import CircleService
from app.application.errors import ApplicationError, RepositoryError
from app.infrastructure.repositories import DemoRepository

@pytest.fixture
def chat():
    repository = DemoRepository()
    repository.user_id = str(uuid4())
    return CircleService(repository), repository

@pytest.mark.asyncio
async def test_idempotent_send_quotes_and_conflicting_retry(chat):
    service, repo = chat
    room = await service.create_circle('Kitchen')
    first = await service.send_message(room['id'], 'Hello')
    token = str(uuid4())
    posted = await service.send_message(room['id'], 'Dinner?', client_id=token, reply_to=first['id'])
    assert posted == await service.send_message(room['id'], 'Dinner?', client_id=token, reply_to=first['id'])
    assert posted['snapshot']['replyTo']['text'] == 'Hello'
    with pytest.raises(RepositoryError, match='Retry content changed'):
        await service.send_message(room['id'], 'Changed', client_id=token)
    other = await service.create_circle('Other room')
    with pytest.raises(RepositoryError, match='another conversation'):
        await service.send_message(other['id'], 'Bad quote', reply_to=first['id'])
    assert len((await service.history(room['id']))['items']) == 2

@pytest.mark.asyncio
async def test_cursor_history_is_stable_and_search_is_authorized(chat):
    service, repo = chat
    room = await service.create_circle('Search')
    posts = [await service.send_message(room['id'], text) for text in ('Rice', 'Beans', 'Rice bowls')]
    await service.comment(posts[0]['id'], 'Sunday lunch')
    page = await service.history(room['id'], limit=2)
    await service.send_message(room['id'], 'New while paging')
    older = await service.history(room['id'], limit=2, cursor=page['nextCursor'])
    assert [p['id'] for p in older['items']] == [posts[0]['id']]
    assert [p['id'] for p in (await service.history(room['id'], query='Sunday'))['items']] == [posts[0]['id']]
    assert len((await service.history(room['id'], query='Rice', kind='message'))['items']) == 2
    with pytest.raises(ApplicationError, match='cursor'):
        await service.history(room['id'], cursor='broken')
    with pytest.raises(RepositoryError):
        await CircleService(repo.as_user(str(uuid4()))).history(room['id'], query='Rice')

@pytest.mark.asyncio
async def test_reads_mute_profiles_reactions_and_edit_access(chat):
    service, repo = chat
    room = await service.create_circle('Friends')
    peer_id = str(uuid4())
    # Model an accepted peer using the same membership epoch rules as invitations.
    repo._circles[room['id']]['members'][peer_id] = 'accepted'
    repo._circles[room['id']]['memberEpochs'][peer_id] = str(uuid4())
    peer = CircleService(repo.as_user(peer_id))
    await service.profile('Alex')
    message = await service.send_message(room['id'], 'Tonight')
    assert (await peer.conversations())['items'][0]['unreadCount'] == 1
    await peer.update_conversation(room['id'], message['id'], True)
    assert (await peer.conversations())['items'][0]['unreadCount'] == 0
    assert (await peer.conversations())['items'][0]['muted'] is True
    await peer.react(message['id'], '👍'); await peer.react(message['id'], '👍')
    assert (await service.history(room['id']))['items'][0]['reactions'][0]['count'] == 1
    assert (await service.history(room['id']))['items'][0]['seenBy'] == 1
    edited = await service.edit_message(message['id'], 'Tomorrow')
    assert edited['snapshot']['text'] == 'Tomorrow' and edited['editedAt']
    assert edited['createdByName'] == 'Alex'
    with pytest.raises(RepositoryError, match='Only your'):
        await peer.edit_message(message['id'], 'Hijack')
    with pytest.raises(ApplicationError): await service.react(message['id'], 'unsupported')
    with pytest.raises(ApplicationError): await service.profile(' ')
    stranger = CircleService(repo.as_user(str(uuid4())))
    with pytest.raises(RepositoryError): await stranger.react(message['id'], '👍')
    with pytest.raises(RepositoryError): await stranger.update_conversation(room['id'], message['id'])
    await service.remove_friend(room['id'], peer_id)
    with pytest.raises(RepositoryError): await peer.history(room['id'])
    assert (await service.history(room['id']))['items'][0]['reactions'] == []

@pytest.mark.asyncio
async def test_direct_shares_reuse_room_and_legacy_rooms_preserve_audience(chat):
    service, repo = chat
    friend = 'friend@example.test'
    first = await service.share_direct(friend, 'recipe', recipe_id=repo._recipes[0]['id'])
    second = await service.share_direct(friend, 'recipe', recipe_id=repo._recipes[0]['id'])
    assert first['circleId'] == second['circleId']
    assert len((await service.conversations())['items']) == 1
    await service.send_message(first['circleId'], 'How was dinner?')
    assert len((await service.history(first['circleId']))['items']) == 3
    with pytest.raises(RepositoryError):
        await CircleService(repo.as_user('outsider@example.test')).history(first['circleId'])
    with pytest.raises(RepositoryError): await service.invite_friend(first['circleId'], 'other@example.test')

@pytest.mark.asyncio
async def test_sync_catches_edits_reactions_and_membership_removal(chat):
    service, repo = chat
    before = await service.sync()
    room = await service.create_circle('Live')
    posted = await service.send_message(room['id'], 'Original')
    after = await service.sync()
    assert before != after
    await service.edit_message(posted['id'], 'Edited')
    assert after != await service.sync()
    stranger = CircleService(repo.as_user(str(uuid4())))
    stranger_before = await stranger.sync()
    await service.react(posted['id'], '👍')
    assert stranger_before == await stranger.sync()



@pytest.mark.asyncio
async def test_legacy_direct_history_is_consolidated_without_widening_frozen_audiences(chat):
    service, repo = chat
    original = await service.share_direct('legacy@example.test', 'recipe', recipe_id=repo._recipes[0]['id'])
    legacy_id = str(uuid4())
    legacy = deepcopy(repo._circles[original['circleId']])
    legacy['id'] = legacy_id
    legacy['memberEpochs'] = {user: str(uuid4()) for user in legacy['members']}
    repo._circles[legacy_id] = legacy
    posted = await service.share_recipe(legacy_id, repo._recipes[0]['id'])
    assert len((await service.conversations())['items']) == 1
    assert len((await service.history(original['circleId']))['items']) == 2
    peer = CircleService(repo.as_user('legacy@example.test'))
    assert len((await peer.history(original['circleId']))['items']) == 2
    await peer.update_conversation(legacy_id, posted['id'], True)
    assert (await peer.conversations())['items'][0]['muted'] is True
    legacy['memberEpochs']['legacy@example.test'] = str(uuid4())
    assert [item['id'] for item in (await peer.history(original['circleId']))['items']] == [original['id']]
    assert len((await service.history(original['circleId']))['items']) == 2
    preview = (await service.conversations())['items'][0]['latest']
    assert preview['snapshot']['recipe']['title']
    assert 'ingredients' not in preview['snapshot']['recipe']
    token = str(uuid4())
    message = await service.send_message(original['circleId'], 'Remove this', client_id=token)
    await service.revoke_share(message['id'])
    with pytest.raises(RepositoryError):
        await service.send_message(original['circleId'], 'Remove this', client_id=token)
