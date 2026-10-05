"""Run capture and RLS behavior in a disposable schema-only database."""
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest


@pytest.mark.skipif(not os.environ.get('MEAL_PREP_TEST_SQL_CONTAINER'), reason='local SQL container not configured')
def test_signal_migration_roundtrip_atomic_history_retries_and_household_scope():
    base = ['docker', 'exec', '-i', os.environ['MEAL_PREP_TEST_SQL_CONTAINER']]
    database = f'signals_test_{uuid4().hex}'
    def run(args, data=None):
        result = subprocess.run(base + args, input=data, capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout
    def sql(query):
        return run(['psql','-U','supabase_admin','-d',database,'-At','-v','ON_ERROR_STOP=1'],query.encode())
    run(['createdb','-U','supabase_admin',database])
    try:
        schema = run(['pg_dump','-U','supabase_admin','--schema-only','--no-owner','--no-publications','--no-subscriptions','postgres'])
        run(['psql','-U','supabase_admin','-d',database,'-v','ON_ERROR_STOP=1'],schema)
        migrations = Path(__file__).resolve().parents[1]/'supabase/migrations'
        if sql("select to_regclass('public.pantry_photo_evidence') is null;").strip() == b't':
            sql((migrations/'202609300003_pantry_photo_evidence.sql').read_text())
        # CI starts with every migration applied; local development may predate this one.
        if sql("select to_regclass('public.household_signal_history') is null;").strip() == b't':
            sql((migrations/'202610050002_household_signals.sql').read_text())
        sql("""
        insert into auth.users(id,email) values
          ('00000000-0000-0000-0000-000000000011','signal-owner@example.test'),
          ('00000000-0000-0000-0000-000000000012','signal-other@example.test');
        set role authenticated;
        select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000011',false);
        select public.create_my_household('Signal test');
        do $$ declare p jsonb; f jsonb; again jsonb; h jsonb; n integer; snapshot jsonb;
          fid uuid := '00000000-0000-0000-0000-000000000021';
          eid uuid := '00000000-0000-0000-0000-000000000022';
          pantry uuid := '00000000-0000-0000-0000-000000000023';
        begin
          p := public.save_meal_plan(jsonb_build_object('weekStart','2030-02-04','entries',jsonb_build_array(
            jsonb_build_object('id',eid,'date','2030-02-04','slot','dinner','slotName','Dinner','meal','Planned lentils','components','[]'::jsonb),
            jsonb_build_object('id','00000000-0000-0000-0000-000000000024','date','2030-02-04','slot','lunch','meal','Soup','components','[]'::jsonb))));
          f := public.save_experience_feedback(jsonb_build_object('id',fid,'mealPlanEntryId',eid,'note','Served rotis instead; no cooking.',
            'feedbackType','change_next_time','inputSource','mcp','occurredOn','2030-02-05',
            'signals','{"goal":"time","actualMinutes":0,"planStatus":"changed","actualMeal":"Rotis","whoCooked":"Arjun","responses":[{"audience":"kids","response":"liked"}],"wasteQuantity":0,"wasteUnit":"portion"}'::jsonb));
          if f->'signals'->>'actualMinutes' <> '0' or f->>'occurred_on' <> '2030-02-05' or f->>'input_source' <> 'mcp' then raise exception 'Reported signals lost'; end if;
          snapshot := f->'plan_snapshot';
          if snapshot->>'title' <> 'Planned lentils' then raise exception 'Plan snapshot missing'; end if;
          select count(*) into n from public.household_signal_history;
          again := public.save_experience_feedback(jsonb_build_object('id',fid,'mealPlanEntryId',eid,'note','Served rotis instead; no cooking.',
            'feedbackType','change_next_time','inputSource','mcp','occurredOn','2030-02-05','signals',f->'signals'));
          if (select count(*) from public.household_signal_history) <> n then raise exception 'Retry duplicated history'; end if;
          begin
            perform public.save_experience_feedback(jsonb_build_object('weekStart','2030-02-04','note','Invalid input','signals','{"actualMinutes":true}'::jsonb));
            raise exception 'Invalid metric accepted';
          exception when check_violation then null; end;
          if (select count(*) from public.household_signal_history) <> n then raise exception 'Failed write recorded history'; end if;
          begin
            perform public.save_reported_feedback(jsonb_build_object('id',fid,'mealPlanEntryId','00000000-0000-0000-0000-000000000024','note','Wrong linked meal'));
            raise exception 'Conflicting meal accepted';
          exception when raise_exception then if sqlerrm <> 'planned meal does not match meal occurrence' then raise; end if; end;
          if (select count(*) from public.household_signal_history) <> n then raise exception 'Conflicting link recorded history'; end if;
          -- Adherence and goal outcomes are independent: skipping a planned meal can help.
          again := public.save_reported_feedback(jsonb_build_object('weekStart','2030-02-04','note','Skipping the plan reduced stress','feedbackType','worked_well','signals','{"goal":"stress","planStatus":"skipped"}'::jsonb));
          if again->'signals'->>'planStatus' <> 'skipped' or again->>'feedback_type' <> 'worked_well' then raise exception 'Adherence overwrote the reported outcome'; end if;
          p := public.save_meal_plan(jsonb_set(p,'{entries,0,meal}','"New dinner"'));
          f := public.save_experience_feedback(jsonb_build_object('id',fid,'mealPlanEntryId',eid,'note','Correction: it was yogurt too.','inputSource','website'));
          if f->'plan_snapshot' <> snapshot or f->'signals'->>'actualMinutes' <> '0' then raise exception 'Correction rewrote original plan or lost metrics'; end if;
          h := public.get_household_signal_history(null,'meal_plan_entries',100);
          if not exists(select 1 from jsonb_array_elements(h) e where e->'before'->>'title' = 'Planned lentils' and e->'after'->>'title' = 'New dinner') then raise exception 'Plan edit history missing'; end if;
          perform public.complete_plan_item('2030-02-04','meal',eid);
          select count(*) into n from public.household_signal_history;
          perform public.complete_plan_item('2030-02-04','meal',eid);
          if (select count(*) from public.household_signal_history) <> n then raise exception 'Completion retry duplicated history'; end if;
          if jsonb_array_length(public.get_household_signal_history(null,'plan_activities',100)) <> 1 then raise exception 'Completion not captured'; end if;
          insert into public.pantry_items(id,household_id,name,quantity,unit) values(pantry,public.active_household_id(),'Yogurt',10,'portion');
          perform public.record_pantry_use(pantry,2);
          select count(*) into n from public.household_signal_history;
          begin perform public.record_pantry_use(pantry,20); raise exception 'Overuse allowed';
          exception when raise_exception then if sqlerrm <> 'Amount used exceeds the remaining quantity' then raise; end if; end;
          if (select count(*) from public.household_signal_history) <> n then raise exception 'Rejected stock write captured'; end if;
          h := public.get_household_signal_history(null,null,1);
          perform set_config('signals.test_owner_cursor',h->0->>'id',false);
          if jsonb_array_length(public.get_household_signal_history((h->0->>'id')::uuid,null,100)) < 1 then raise exception 'History paging failed'; end if;
          begin insert into public.household_signal_history(household_id,source_table,source_id,operation) values(public.active_household_id(),'feedback_entries',fid,'insert');
            raise exception 'Client forged history'; exception when insufficient_privilege then null; end;
        end $$;
        select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000012',false);
        select public.create_my_household('Other test');
        do $$ begin
          if public.get_experience_feedback() <> '[]'::jsonb then raise exception 'Other feedback visible'; end if;
          if exists(select 1 from public.household_signal_history where source_table='feedback_entries') then raise exception 'Other history visible'; end if;
          begin perform public.get_household_signal_history(current_setting('signals.test_owner_cursor')::uuid,null,10);
            raise exception 'Foreign cursor accepted'; exception when raise_exception then
              if sqlerrm <> 'History cursor was not found in this household' then raise; end if; end;
        end $$;
        """)
    finally:
        run(['dropdb','-U','supabase_admin',database])
