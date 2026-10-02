"""Opt-in migration check in an isolated schema-only copy of local Postgres."""
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest


@pytest.mark.skipif(not os.environ.get('MEAL_PREP_TEST_SQL_CONTAINER'), reason='local SQL container not configured')
def test_nutrition_sql_roundtrip_completed_guard_and_household_scope():
    container = os.environ['MEAL_PREP_TEST_SQL_CONTAINER']
    database = f'nutrition_test_{uuid4().hex}'
    base = ['docker', 'exec', '-i', container]

    def run(args, data=None):
        result = subprocess.run(base + args, input=data, capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout

    def sql(query):
        return run(['psql', '-U', 'supabase_admin', '-d', database, '-At', '-v', 'ON_ERROR_STOP=1'], query.encode())

    run(['createdb', '-U', 'supabase_admin', database])
    try:
        # No household data, tokens, or auth records are copied into the test database.
        schema = run(['pg_dump', '-U', 'supabase_admin', '--schema-only', '--no-owner',
                      '--no-publications', '--no-subscriptions', 'postgres'])
        run(['psql', '-U', 'supabase_admin', '-d', database, '-v', 'ON_ERROR_STOP=1'], schema)
        migrations = Path(__file__).resolve().parents[1] / 'supabase/migrations'
        for relation, filename in [('public.meals', '202610020002_reusable_meals.sql'),
                                    ('public.friend_circles', '202610020003_friend_circles.sql')]:
            if sql(f"select to_regclass('{relation}') is null;").strip() == b't':
                sql((migrations / filename).read_text())
        if sql("select count(*) from information_schema.columns where table_schema='public' and table_name='meal_plan_entries' and column_name='nutrition';").strip() == b'0':
            sql((migrations / '202610020007_meal_nutrition.sql').read_text())
        sql("""
        do $$
        declare
          u uuid := gen_random_uuid(); other_user uuid := gen_random_uuid(); meal_id uuid := gen_random_uuid();
          plan jsonb; completed jsonb; guide jsonb := '{"basis":"Ingredient estimate","profiles":[{"name":"Adults","serving":"Add tofu","portion":"1 bowl","valueType":"estimated","amounts":{"protein":35,"fat":0,"calories":520},"macros":{"protein":"high"},"micronutrients":[{"nutrient":"Iron","source":"Tofu","amount":3.2,"unit":"mg"}]}]}';
        begin
          insert into auth.users(id, email) values (u, u::text || '@example.test'), (other_user, other_user::text || '@example.test');
          perform set_config('request.jwt.claim.sub', u::text, true);
          perform public.create_my_household('Nutrition test');
          insert into public.recipes(household_id, title, nutrition) values (public.active_household_id(), 'Recipe numbers', guide);
          if (select nutrition from public.recipes where title = 'Recipe numbers') is distinct from guide then raise exception 'Recipe nutrition lost'; end if;
          begin
            update public.recipes set nutrition = '[]'::jsonb where title = 'Recipe numbers';
            raise exception 'Invalid recipe nutrition accepted';
          exception when check_violation then null; end;

          plan := public.save_meal_plan(jsonb_build_object('weekStart','2045-02-06','entries',jsonb_build_array(
            jsonb_build_object('id',meal_id,'date','2045-02-06','slot','dinner','slotName','Dinner','meal','Noodles','components','[]'::jsonb,'nutrition',guide))));
          if plan->'entries'->0->'nutrition' is distinct from guide then raise exception 'Nutrition save lost data'; end if;
          if public.get_meal_plan('2045-02-06')->'entries'->0->'nutrition' is distinct from guide then raise exception 'Nutrition read lost data'; end if;
          begin
            perform public.save_meal_plan(jsonb_set(plan,'{entries,0,nutrition}','[]'::jsonb));
            raise exception 'Invalid nutrition accepted';
          exception when check_violation then null; end;
          if public.get_meal_plan('2045-02-06')->'entries'->0->'nutrition' is distinct from guide then raise exception 'Failure changed nutrition'; end if;
          completed := public.complete_plan_item('2045-02-06','meal',meal_id)->'plan';
          if completed->'entries'->0->'nutrition' is distinct from guide then raise exception 'Completion lost nutrition'; end if;
          begin
            perform public.save_meal_plan(jsonb_set(completed,'{entries,0,nutrition}','null'::jsonb));
            raise exception 'Completed nutrition edit accepted';
          exception when raise_exception then
            if sqlerrm <> 'Completed plan items cannot be edited' then raise; end if;
          end;
          perform set_config('request.jwt.claim.sub', other_user::text, true);
          perform public.create_my_household('Other household');
          if public.get_meal_plan('2045-02-06') is not null then raise exception 'Cross household plan visible'; end if;
        end $$;
        """)
    finally:
        run(['dropdb', '-U', 'supabase_admin', database])
