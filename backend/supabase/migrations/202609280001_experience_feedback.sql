-- Experience learning is graph-shaped but remains relational:
-- recipes -> variants -> meal occurrences -> feedback -> canonical tags.

create table public.recipe_variants (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 120),
  variant_key text generated always as (lower(trim(name))) stored,
  adaptations jsonb not null default '[]'::jsonb check (jsonb_typeof(adaptations) = 'array'),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (household_id, recipe_id, variant_key)
);

create table public.meal_occurrences (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  meal_plan_entry_id uuid references public.meal_plan_entries(id) on delete set null,
  weekly_schedule_id uuid references public.weekly_schedules(id) on delete set null,
  week_start date,
  occurred_on date,
  slot text,
  title text not null check (char_length(title) between 1 and 180),
  recipe_id uuid references public.recipes(id) on delete set null,
  recipe_variant_id uuid references public.recipe_variants(id) on delete set null,
  variation_snapshot jsonb not null default '{}'::jsonb check (jsonb_typeof(variation_snapshot) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (meal_plan_entry_id),
  check (recipe_variant_id is null or recipe_id is not null)
);

create table public.feedback_entries (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  occurrence_id uuid references public.meal_occurrences(id) on delete set null,
  weekly_schedule_id uuid references public.weekly_schedules(id) on delete set null,
  week_start date,
  feedback_type text not null default 'change_next_time'
    check (feedback_type in ('worked_well', 'change_next_time', 'problem', 'preference')),
  note text not null check (char_length(note) between 1 and 600),
  next_time text not null default '' check (char_length(next_time) <= 600),
  rating integer check (rating is null or rating between 1 and 5),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (occurrence_id is not null or week_start is not null)
);

create table public.feedback_tags (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  slug text not null check (slug ~ '^[a-z0-9][a-z0-9:_-]{0,47}$'),
  label text not null check (char_length(label) between 1 and 80),
  facet text not null default 'other'
    check (facet in ('outcome', 'taste', 'texture', 'operations', 'audience', 'adaptation', 'other')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (household_id, slug)
);

create table public.feedback_entry_tags (
  feedback_id uuid not null references public.feedback_entries(id) on delete cascade,
  tag_id uuid not null references public.feedback_tags(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (feedback_id, tag_id)
);

create trigger recipe_variants_touch before update on public.recipe_variants
for each row execute function public.touch_updated_at();
create trigger meal_occurrences_touch before update on public.meal_occurrences
for each row execute function public.touch_updated_at();
create trigger feedback_entries_touch before update on public.feedback_entries
for each row execute function public.touch_updated_at();
create trigger feedback_tags_touch before update on public.feedback_tags
for each row execute function public.touch_updated_at();

alter table public.recipe_variants enable row level security;
alter table public.meal_occurrences enable row level security;
alter table public.feedback_entries enable row level security;
alter table public.feedback_tags enable row level security;
alter table public.feedback_entry_tags enable row level security;

create policy recipe_variants_all on public.recipe_variants for all to authenticated
  using (public.is_household_member(household_id))
  with check (
    public.is_household_member(household_id)
    and exists (
      select 1 from public.recipes r
      where r.id = recipe_id and r.household_id = recipe_variants.household_id
    )
  );

create policy meal_occurrences_all on public.meal_occurrences for all to authenticated
  using (public.is_household_member(household_id))
  with check (
    public.is_household_member(household_id)
    and (recipe_id is null or exists (
      select 1 from public.recipes r
      where r.id = recipe_id and r.household_id = meal_occurrences.household_id
    ))
    and (recipe_variant_id is null or exists (
      select 1 from public.recipe_variants v
      where v.id = recipe_variant_id
        and v.recipe_id = meal_occurrences.recipe_id
        and v.household_id = meal_occurrences.household_id
    ))
    and (meal_plan_entry_id is null or exists (
      select 1 from public.meal_plan_entries e
      join public.meal_plans p on p.id = e.meal_plan_id
      where e.id = meal_plan_entry_id and p.household_id = meal_occurrences.household_id
    ))
    and (weekly_schedule_id is null or exists (
      select 1 from public.weekly_schedules s
      where s.id = weekly_schedule_id and s.household_id = meal_occurrences.household_id
    ))
  );

create policy feedback_entries_all on public.feedback_entries for all to authenticated
  using (public.is_household_member(household_id))
  with check (
    public.is_household_member(household_id)
    and (occurrence_id is null or exists (
      select 1 from public.meal_occurrences o
      where o.id = occurrence_id and o.household_id = feedback_entries.household_id
    ))
    and (weekly_schedule_id is null or exists (
      select 1 from public.weekly_schedules s
      where s.id = weekly_schedule_id and s.household_id = feedback_entries.household_id
    ))
  );

create policy feedback_tags_all on public.feedback_tags for all to authenticated
  using (public.is_household_member(household_id))
  with check (public.is_household_member(household_id));

create policy feedback_entry_tags_all on public.feedback_entry_tags for all to authenticated
  using (exists (
    select 1 from public.feedback_entries f
    join public.feedback_tags t on t.household_id = f.household_id
    where f.id = feedback_id and t.id = tag_id and public.is_household_member(f.household_id)
  ))
  with check (exists (
    select 1 from public.feedback_entries f
    join public.feedback_tags t on t.household_id = f.household_id
    where f.id = feedback_id and t.id = tag_id and public.is_household_member(f.household_id)
  ));

create index recipe_variants_recipe_idx
  on public.recipe_variants (household_id, recipe_id, updated_at desc);
create index meal_occurrences_recipe_idx
  on public.meal_occurrences (household_id, recipe_id, occurred_on desc nulls last);
create index meal_occurrences_week_idx
  on public.meal_occurrences (household_id, week_start, occurred_on desc nulls last);
create index feedback_entries_household_created_idx
  on public.feedback_entries (household_id, created_at desc);
create index feedback_entries_occurrence_idx on public.feedback_entries (occurrence_id);
create index feedback_entries_week_idx
  on public.feedback_entries (household_id, week_start, created_at desc);
create index feedback_tags_facet_idx on public.feedback_tags (household_id, facet, slug);
create index feedback_entry_tags_tag_idx on public.feedback_entry_tags (tag_id, feedback_id);

grant select, insert, update, delete on table public.recipe_variants to authenticated;
grant select, insert, update, delete on table public.meal_occurrences to authenticated;
grant select, insert, update, delete on table public.feedback_entries to authenticated;
grant select, insert, update, delete on table public.feedback_tags to authenticated;
grant select, insert, update, delete on table public.feedback_entry_tags to authenticated;

-- One transaction creates or reuses the occurrence, canonicalizes tag nodes,
-- and connects all edges. The caller has already normalized tag aliases.
create or replace function public.save_experience_feedback(feedback jsonb)
returns jsonb
language plpgsql
security invoker
as $$
declare
  target_household_id uuid;
  target_feedback_id uuid := coalesce(nullif(feedback->>'id', '')::uuid, gen_random_uuid());
  target_occurrence_id uuid;
  target_schedule_id uuid;
  target_recipe_id uuid := nullif(feedback->>'recipeId', '')::uuid;
  occurrence_recipe_id uuid;
  occurrence_week_start date;
  target_variant_id uuid;
  target_plan_entry_id uuid := nullif(feedback->>'mealPlanEntryId', '')::uuid;
  target_week_start date := nullif(feedback->>'weekStart', '')::date;
  target_occurred_on date := nullif(feedback->>'occurredOn', '')::date;
  target_slot text := nullif(trim(feedback->>'slot'), '');
  target_title text := nullif(trim(feedback->>'mealTitle'), '');
  variant_name text := nullif(trim(feedback->>'variantName'), '');
  variant_adaptations jsonb := coalesce(feedback->'adaptations', '[]'::jsonb);
  tag_record jsonb;
  target_tag_id uuid;
  result jsonb;
begin
  select household_id into target_household_id
  from public.household_members
  where user_id = auth.uid()
  order by joined_at
  limit 1;
  if target_household_id is null then raise exception 'household required'; end if;

  target_occurrence_id := nullif(feedback->>'occurrenceId', '')::uuid;
  if target_occurrence_id is null and nullif(feedback->>'id', '') is not null then
    select occurrence_id into target_occurrence_id
    from public.feedback_entries
    where id = target_feedback_id and household_id = target_household_id;
  end if;
  if target_occurrence_id is not null then
    select
      o.recipe_id, o.week_start, coalesce(target_occurred_on, o.occurred_on),
      coalesce(target_slot, o.slot), coalesce(target_title, o.title)
    into occurrence_recipe_id, occurrence_week_start, target_occurred_on, target_slot, target_title
    from public.meal_occurrences o
    where o.id = target_occurrence_id and o.household_id = target_household_id;
    if not found then raise exception 'meal occurrence was not found'; end if;
    if target_recipe_id is not null and occurrence_recipe_id is distinct from target_recipe_id then
      raise exception 'recipe does not match meal occurrence';
    end if;
    if target_week_start is not null and occurrence_week_start is not null
      and occurrence_week_start <> target_week_start then
      raise exception 'week does not match meal occurrence';
    end if;
    target_recipe_id := coalesce(target_recipe_id, occurrence_recipe_id);
    target_week_start := coalesce(target_week_start, occurrence_week_start);
  end if;

  if target_plan_entry_id is not null then
    select e.recipe_id, e.title, e.planned_for, e.slot, p.week_start
      into target_recipe_id, target_title, target_occurred_on, target_slot, target_week_start
    from public.meal_plan_entries e
    join public.meal_plans p on p.id = e.meal_plan_id
    where e.id = target_plan_entry_id and p.household_id = target_household_id;
    if not found then raise exception 'meal-plan entry was not found'; end if;
  end if;

  if target_recipe_id is not null then
    select coalesce(target_title, r.title) into target_title
    from public.recipes r
    where r.id = target_recipe_id and r.household_id = target_household_id;
    if not found then raise exception 'recipe was not found'; end if;
  end if;

  if target_week_start is not null then
    select id into target_schedule_id
    from public.weekly_schedules
    where household_id = target_household_id and week_start = target_week_start;
  end if;

  if variant_name is not null then
    if target_recipe_id is null then raise exception 'variant requires a recipe'; end if;
    insert into public.recipe_variants (household_id, recipe_id, name, adaptations, created_by)
    values (target_household_id, target_recipe_id, variant_name, variant_adaptations, auth.uid())
    on conflict (household_id, recipe_id, variant_key) do update
      set adaptations = case
        when jsonb_array_length(excluded.adaptations) > 0 then excluded.adaptations
        else public.recipe_variants.adaptations
      end,
      updated_at = now()
    returning id into target_variant_id;
    select adaptations into variant_adaptations
    from public.recipe_variants where id = target_variant_id;
  end if;

  if target_occurrence_id is null and (target_recipe_id is not null or target_plan_entry_id is not null) then
    if target_plan_entry_id is not null then
      select id into target_occurrence_id
      from public.meal_occurrences
      where meal_plan_entry_id = target_plan_entry_id;
    end if;
    if target_occurrence_id is null then
      insert into public.meal_occurrences (
        household_id, meal_plan_entry_id, weekly_schedule_id, week_start,
        occurred_on, slot, title, recipe_id, recipe_variant_id, variation_snapshot
      ) values (
        target_household_id, target_plan_entry_id, target_schedule_id, target_week_start,
        target_occurred_on, target_slot, coalesce(target_title, 'Meal'), target_recipe_id,
        target_variant_id,
        case when target_variant_id is null then '{}'::jsonb else jsonb_build_object(
          'name', variant_name, 'adaptations', variant_adaptations
        ) end
      ) returning id into target_occurrence_id;
    end if;
  end if;

  if target_occurrence_id is not null and target_variant_id is not null then
    update public.meal_occurrences set
      recipe_variant_id = target_variant_id,
      variation_snapshot = jsonb_build_object(
        'name', variant_name, 'adaptations', variant_adaptations
      )
    where id = target_occurrence_id and household_id = target_household_id;
  end if;

  insert into public.feedback_entries (
    id, household_id, occurrence_id, weekly_schedule_id, week_start,
    feedback_type, note, next_time, rating, created_by
  ) values (
    target_feedback_id, target_household_id, target_occurrence_id, target_schedule_id,
    target_week_start, coalesce(feedback->>'feedbackType', 'change_next_time'),
    trim(feedback->>'note'), coalesce(trim(feedback->>'nextTime'), ''),
    nullif(feedback->>'rating', '')::integer, auth.uid()
  )
  on conflict (id) do update set
    occurrence_id = excluded.occurrence_id,
    weekly_schedule_id = excluded.weekly_schedule_id,
    week_start = excluded.week_start,
    feedback_type = excluded.feedback_type,
    note = excluded.note,
    next_time = excluded.next_time,
    rating = excluded.rating,
    updated_at = now()
  where public.feedback_entries.household_id = target_household_id;

  delete from public.feedback_entry_tags where feedback_id = target_feedback_id;
  for tag_record in select value from jsonb_array_elements(coalesce(feedback->'tagRecords', '[]'::jsonb)) loop
    insert into public.feedback_tags (household_id, slug, label, facet)
    values (
      target_household_id, tag_record->>'slug', tag_record->>'label',
      coalesce(tag_record->>'facet', 'other')
    )
    on conflict (household_id, slug) do update set
      label = excluded.label, facet = excluded.facet, updated_at = now()
    returning id into target_tag_id;
    insert into public.feedback_entry_tags (feedback_id, tag_id)
    values (target_feedback_id, target_tag_id)
    on conflict do nothing;
  end loop;

  select (to_jsonb(f) - 'household_id' - 'created_by') || jsonb_build_object(
    'tags', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', t.id, 'slug', t.slug, 'label', t.label, 'facet', t.facet
      ) order by t.facet, t.slug)
      from public.feedback_entry_tags ft
      join public.feedback_tags t on t.id = ft.tag_id
      where ft.feedback_id = f.id
    ), '[]'::jsonb),
    'occurrence', case when o.id is null then null else
      (to_jsonb(o) - 'household_id') || jsonb_build_object(
        'variant', case when v.id is null then null else
          (to_jsonb(v) - 'household_id' - 'created_by')
        end
      )
    end
  ) into result
  from public.feedback_entries f
  left join public.meal_occurrences o on o.id = f.occurrence_id
  left join public.recipe_variants v on v.id = o.recipe_variant_id
  where f.id = target_feedback_id and f.household_id = target_household_id;

  if result is null then raise exception 'feedback could not be saved'; end if;
  return result;
end;
$$;

create or replace function public.get_experience_feedback(
  requested_recipe_id uuid default null,
  requested_week_start date default null,
  requested_tags text[] default null,
  requested_feedback_type text default null,
  result_limit integer default 20
)
returns jsonb
language sql
stable
security invoker
as $$
  with target_household as (
    select household_id
    from public.household_members
    where user_id = auth.uid()
    order by joined_at
    limit 1
  ), matching as (
    select f.*, o.recipe_id, o.id as joined_occurrence_id,
      (to_jsonb(o) - 'household_id') || jsonb_build_object(
        'variant', case when v.id is null then null else
          (to_jsonb(v) - 'household_id' - 'created_by')
        end
      ) as occurrence
    from public.feedback_entries f
    left join public.meal_occurrences o on o.id = f.occurrence_id
    left join public.recipe_variants v on v.id = o.recipe_variant_id
    where f.household_id = (select household_id from target_household)
      and (requested_recipe_id is null or o.recipe_id = requested_recipe_id)
      and (requested_week_start is null or coalesce(f.week_start, o.week_start) = requested_week_start)
      and (requested_feedback_type is null or f.feedback_type = requested_feedback_type)
      and (
        requested_tags is null
        or not exists (
          select 1 from unnest(requested_tags) requested_slug
          where not exists (
            select 1
            from public.feedback_entry_tags ft
            join public.feedback_tags t on t.id = ft.tag_id
            where ft.feedback_id = f.id and t.slug = requested_slug
          )
        )
      )
    order by f.created_at desc
    limit least(greatest(result_limit, 1), 100)
  )
  select coalesce(jsonb_agg(
    (to_jsonb(matching) - 'household_id' - 'created_by' - 'recipe_id' - 'joined_occurrence_id' - 'occurrence')
    || jsonb_build_object(
      'occurrence', case when matching.joined_occurrence_id is null then null else matching.occurrence end,
      'tags', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', t.id, 'slug', t.slug, 'label', t.label, 'facet', t.facet
        ) order by t.facet, t.slug)
        from public.feedback_entry_tags ft
        join public.feedback_tags t on t.id = ft.tag_id
        where ft.feedback_id = matching.id
      ), '[]'::jsonb)
    ) order by matching.created_at desc
  ), '[]'::jsonb)
  from matching;
$$;

grant execute on function public.save_experience_feedback(jsonb) to authenticated;
grant execute on function public.get_experience_feedback(uuid, date, text[], text, integer) to authenticated;

alter table public.household_memories
  drop constraint household_memories_source_type_check;
alter table public.household_memories
  add constraint household_memories_source_type_check
  check (source_type in ('user', 'onboarding', 'schedule', 'retro', 'feedback', 'observation'));
