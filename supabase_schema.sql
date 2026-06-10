create table if not exists public.lotto_app_state (
    state_key text primary key,
    updated_at timestamptz not null default timezone('utc', now()),
    payload_json jsonb not null
);

create table if not exists public.lotto_log_records (
    record_uid text primary key,
    timestamp_utc timestamptz null,
    timestamp_kst text null,
    log_type text not null,
    run_id text null,
    source_round integer null,
    target_round integer null,
    candidate_rank integer null,
    score_metric double precision null,
    score double precision null,
    best_score double precision null,
    average_score double precision null,
    probability_score double precision null,
    input_order_score double precision null,
    avg_gap_factor double precision null,
    avg_probability_weight double precision null,
    numbers_json jsonb not null default '[]'::jsonb,
    input_numbers_json jsonb not null default '[]'::jsonb,
    best_order_json jsonb not null default '[]'::jsonb,
    matched_numbers_json jsonb not null default '[]'::jsonb,
    payload_json jsonb not null
);

create index if not exists idx_lotto_log_records_timestamp_utc
    on public.lotto_log_records (timestamp_utc desc);

create index if not exists idx_lotto_log_records_type_timestamp
    on public.lotto_log_records (log_type, timestamp_utc desc);

alter table public.lotto_app_state enable row level security;
alter table public.lotto_log_records enable row level security;

-- 서버 키를 사용하는 경우 별도 policy 없이도 동작합니다.
-- anon key를 사용할 경우 필요한 정책을 추가하세요.
