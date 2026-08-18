-- Shareholding tracker schema
-- Run this once in the Supabase SQL editor (Project > SQL Editor > New query).

-- 1. Your watchlist: which investor is behind which named entity.
create table if not exists sht_watchlist_entities (
  id            bigint generated always as identity primary key,
  investor      text not null,
  entity        text not null,
  entity_norm   text generated always as (lower(trim(entity))) stored,
  created_at    timestamptz not null default now(),
  unique (investor, entity)
);

-- 2. The repository: one row per (entity, company, quarter) as filed.
create table if not exists sht_holdings (
  id              bigint generated always as identity primary key,
  symbol          text not null,
  company         text not null,
  entity          text not null,
  investor        text,                          -- filled in once matched to your watchlist
  watchlist_id    bigint references sht_watchlist_entities(id),
  category        text,                           -- e.g. "Public-Institution (Foreign): FPI Category I"
  pct             numeric(6,3) not null,
  shares          bigint not null,
  prev_pct        numeric(6,3),
  quarter_end     date not null,
  status          text not null check (status in ('new','added','sold','existing')),
  source_url      text,                            -- the XBRL filing this row came from
  fetched_at      timestamptz not null default now(),
  unique (symbol, entity, quarter_end)
);

create index if not exists sht_holdings_investor_idx on sht_holdings (investor);
create index if not exists sht_holdings_symbol_idx on sht_holdings (symbol);
create index if not exists sht_holdings_quarter_idx on sht_holdings (quarter_end);

-- 3. Review queue: near-matches the fuzzy matcher isn't confident enough to
--    auto-attribute. You confirm or reject these in the Input tab; nothing
--    here counts as a real signal until you do.
create table if not exists sht_review_queue (
  id              bigint generated always as identity primary key,
  symbol          text not null,
  company         text not null,
  raw_holder_name text not null,
  category        text,
  pct             numeric(6,3),
  shares          bigint,
  quarter_end     date not null,
  candidate_watchlist_id bigint references sht_watchlist_entities(id),
  similarity      numeric(5,2),                    -- 0-100 fuzzy match score
  resolved        boolean not null default false,
  created_at      timestamptz not null default now()
);

-- 4. Run log: one row per scrape run, for debugging when something fails
--    silently in GitHub Actions.
create table if not exists sht_scrape_log (
  id            bigint generated always as identity primary key,
  run_started   timestamptz not null default now(),
  symbols_total int,
  symbols_ok    int,
  symbols_failed int,
  new_holdings  int,
  review_added  int,
  notes         text
);

-- Row Level Security: since this is a personal single-user tool accessed via
-- a service-role key from GitHub Actions and an anon key from the dashboard,
-- keep RLS on but permissive. Tighten this if you ever add real auth.
alter table sht_watchlist_entities enable row level security;
alter table sht_holdings enable row level security;
alter table sht_review_queue enable row level security;
alter table sht_scrape_log enable row level security;

create policy "allow all on sht_watchlist_entities" on sht_watchlist_entities for all using (true) with check (true);
create policy "allow all on sht_holdings" on sht_holdings for all using (true) with check (true);
create policy "allow all on sht_review_queue" on sht_review_queue for all using (true) with check (true);
create policy "allow all on sht_scrape_log" on sht_scrape_log for all using (true) with check (true);
