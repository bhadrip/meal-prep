from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import httpx
import pytest

from app.application.errors import ApplicationError, RepositoryError, StorageNotInstalledError
from app.application.services import FeedbackService, PlanningService, RecipePantryService
from app.application.signals import capture_contract
from app.config import Settings
from app.infrastructure import repositories
from app.infrastructure.repositories import DemoRepository, SupabaseRepository, _repository_error
from app.main import app


@pytest.fixture
def repo(monkeypatch):
    for name in ('_feedback','_feedback_tags','_occurrences','_variants','_pantry_photos','_memories'):
        monkeypatch.setattr(DemoRepository,name,[])
    value=DemoRepository()
    monkeypatch.setattr(repositories,'demo_repository',lambda:value)
    return value


@pytest.fixture
def client(repo):
    return TestClient(app)


@pytest.mark.asyncio
async def test_reported_metrics_goal_date_source_and_frozen_plan_survive_corrections_and_retry(repo):
    planner=PlanningService(repo)
    eid=str(uuid4())
    plan=await planner.save_meal_plan({'weekStart':'2030-02-04','entries':[{'id':eid,'date':'2030-02-04','slot':'dinner','meal':'Planned lentils','components':[]}]})
    feedback=FeedbackService(repo)
    args={'id':str(uuid4()),'mealPlanEntryId':eid,'note':'Changed dinner and it helped.','feedbackType':'worked_well','occurredOn':'2030-02-05',
          'signals':{'goal':'stress','planStatus':'skipped','stressBefore':5,'stressAfter':2,'actualMinutes':0,'actualMeal':'Rotis','whoCooked':'Arjun','responses':[{'audience':'kids','response':'mixed'}],'wasteQuantity':0,'wasteUnit':'portion','actualCost':0,'currency':'USD'}}
    saved=await feedback.save(args,input_source='mcp')
    assert saved['signals']['actualMinutes']==0 and saved['input_source']=='mcp'
    assert saved['week_start']=='2030-02-04' and saved['occurred_on']=='2030-02-05'
    assert saved['plan_snapshot']['meal']=='Planned lentils'
    count=len(repo._signal_history)
    assert await feedback.save(args,input_source='mcp')==saved
    assert len(repo._signal_history)==count
    plan['entries'][0]['meal']='New planned dinner'
    await planner.save_meal_plan(plan)
    corrected=await feedback.save({'id':saved['id'],'occurrenceId':saved['occurrence_id'],'note':'It was yogurt too.','feedbackType':'worked_well'},input_source='website')
    assert corrected['signals']==saved['signals']
    assert corrected['plan_snapshot']==saved['plan_snapshot']
    history=(await feedback.history(source_table='feedback_entries'))['items']
    assert history[0]['before']['note']==args['note'] and history[0]['after']['note']=='It was yogurt too.'
    assert history[0]['inputSource']=='website'


@pytest.mark.asyncio
@pytest.mark.parametrize('signals',[
    {'actualMinutes':True},{'actualMinutes':1.5},{'actualMinutes':-1},{'effort':6},{'stressAfter':0},
    {'goal':'invented'},{'goal':'other'},{'wasteQuantity':2},{'actualCost':12},{'currency':'usd'},
    {'actualCost':float('inf'),'currency':'USD'},{'context':['flu_season']},{'context':['guests','guests']},
    {'responses':[{'audience':'kids','response':'probably_liked'}]},
    {'responses':[{'audience':'kids','response':'liked'},{'audience':'Kids','response':'mixed'}]},
    {'startedAt':'2026-10-05T18:00:00'},
    {'startedAt':'2026-10-05T19:00:00-07:00','finishedAt':'2026-10-05T18:00:00-07:00'},
    {'confidence':.95}, [],
])
async def test_invalid_or_inferred_metrics_publish_nothing(repo,signals):
    before=deepcopy(repo._signal_history)
    with pytest.raises(ApplicationError,match='signals'):
        await FeedbackService(repo).save({'weekStart':'2030-02-04','note':'My original report.','signals':signals})
    assert repo._signal_history==before and await repo.get_feedback()==[]


@pytest.mark.asyncio
async def test_context_update_is_not_success_and_capture_has_paged_history_and_failed_writes(repo):
    feedback=FeedbackService(repo)
    observation=await feedback.save({'weekStart':'2030-02-04','feedbackType':'context_update','note':'Guests on Friday.','signals':{'context':['guests']}})
    assert observation['signals']=={'context':['guests']}
    assert (await feedback.what_worked('2030-02-04'))['items']==[]
    await feedback.save({'id':observation['id'],'weekStart':'2030-02-04','feedbackType':'context_update','note':'Correction: Saturday.'})
    first=await feedback.history(limit=1)
    older=await feedback.history(before_id=first['nextCursor'],limit=1)
    assert first['hasMore'] and first['items'][0]['id']!=older['items'][0]['id']
    before=deepcopy(repo._signal_history)
    with pytest.raises(RepositoryError):
        await feedback.history(before_id=str(uuid4()))
    with pytest.raises(ApplicationError):
        await feedback.history(source_table='auth_users')
    with pytest.raises(ApplicationError):
        await feedback.save({'weekStart':'2030-02-04','note':'Report','occurredOn':'not-a-date'})
    assert repo._signal_history==before
    item=await RecipePantryService(repo).update_pantry_item({'name':'Lentils','quantity':1,'unit':'cup'})
    before=deepcopy(repo._signal_history)
    with pytest.raises(ApplicationError):
        await RecipePantryService(repo).record_pantry_use(item['id'],2)
    assert repo._signal_history==before


@pytest.mark.asyncio
async def test_multiple_reports_share_the_planned_occurrence_and_conflicting_links_leave_no_event(repo):
    entries=[{'id':str(uuid4()),'date':'2030-02-04','slot':slot,'meal':title,'components':[]}
             for slot,title in [('lunch','Soup'),('dinner','Lentils')]]
    await PlanningService(repo).save_meal_plan({'weekStart':'2030-02-04','entries':entries})
    feedback=FeedbackService(repo)
    first=await feedback.save({'mealPlanEntryId':entries[0]['id'],'note':'Kids liked it.'})
    second=await feedback.save({'mealPlanEntryId':entries[0]['id'],'note':'Cleanup took longer.'})
    assert first['occurrence_id']==second['occurrence_id'] and len(repo._occurrences)==1
    before=deepcopy(repo._signal_history)
    with pytest.raises(RepositoryError,match='does not match'):
        await feedback.save({'id':first['id'],'mealPlanEntryId':entries[1]['id'],'note':'Wrong linked meal.'})
    assert repo._signal_history==before


@pytest.mark.asyncio
async def test_demo_history_excludes_private_photo_paths_and_source_file_ids(repo):
    photo=await repo.save_pantry_photo(image=b'mock',width=1,height=1,file_id='file-private',note='Mock pantry',observations=[],apply_to_pantry=False)
    row=repo._pantry_photos[0]
    row.update({'source_file_id':'file-private','object_path':'private/photo.jpg'})
    await repo.apply_pantry_photo(photo['id'],[{'name':'Lentils','quantity':1,'unit':'cup'}])
    event=(await FeedbackService(repo).history(source_table='pantry_photo_evidence'))['items'][0]
    assert event['after']['status']=='applied'
    for snapshot in (event['before'],event['after']):
        assert 'source_file_id' not in snapshot and 'object_path' not in snapshot


def test_http_capture_preserves_zero_unknowns_and_transport_source(client):
    args={'id':str(uuid4()),'weekStart':'2030-02-04','feedbackType':'context_update','note':'Arjun can help.','signals':{'actualMinutes':0},'inputSource':'forged'}
    response=client.post('/api/feedback',json=args)
    assert response.status_code==200
    saved=response.json()
    assert saved['input_source']=='website' and saved['signals']=={'actualMinutes':0}
    assert saved['occurred_on'] is None
    assert client.post('/api/feedback',json={**args,'signals':{'actualMinutes':True}}).status_code==422
    assert client.get('/api/signals/history?source_table=feedback_entries').json()['items'][0]['after']['signals']=={'actualMinutes':0}
    assert client.get('/api/signals/contract').json()==capture_contract()
    assert client.get('/api/signals/history?before_id=bad').status_code==422


@pytest.mark.asyncio
async def test_repository_uses_versioned_capture_rpc_and_missing_migration_cannot_silently_drop_fields(monkeypatch):
    repo=SupabaseRepository(Settings(supabase_url='https://example.supabase.co',supabase_anon_key='test',_env_file=None),'token')
    rpc=AsyncMock(return_value={'id':'saved','signals':{'actualMinutes':0}})
    monkeypatch.setattr(repo,'rpc',rpc)
    payload={'note':'Report','signals':{'actualMinutes':0}}
    assert (await repo.save_feedback(payload))['signals']==payload['signals']
    rpc.assert_awaited_once_with('save_reported_feedback',{'feedback':payload})
    request=httpx.Request('POST','https://example.supabase.co/rest/v1/rpc/save_reported_feedback')
    response=httpx.Response(404,request=request,json={'code':'PGRST202','message':'Missing function'})
    error=_repository_error('rpc/save_reported_feedback',httpx.HTTPStatusError('missing',request=request,response=response))
    assert isinstance(error,StorageNotInstalledError) and error.feature=='household signals'
    rpc.reset_mock();rpc.side_effect=error
    with pytest.raises(StorageNotInstalledError):
        await repo.save_feedback(payload)
    assert rpc.await_count==1
