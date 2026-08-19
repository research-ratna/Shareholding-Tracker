import { createClient } from "@supabase/supabase-js";

// NEXT_PUBLIC_ vars are safe to expose to the browser - this must be the
// anon key (read/write governed by the permissive RLS policies in
// schema.sql), never the service-role key used by the scraper.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(url, anonKey);

export type WatchlistRow = {
  id: number;
  investor: string;
  entity: string;
};

export type HoldingRow = {
  id: number;
  symbol: string;
  company: string;
  entity: string;
  investor: string | null;
  category: string | null;
  pct: number;
  shares: number;
  prev_pct: number | null;
  quarter_end: string;
  status: "new" | "added" | "sold" | "existing";
};

export type ReviewRow = {
  id: number;
  symbol: string;
  company: string;
  raw_holder_name: string;
  category: string | null;
  pct: number | null;
  shares: number | null;
  quarter_end: string;
  candidate_watchlist_id: number | null;
  similarity: number | null;
  resolved: boolean;
};

export type CompanyWatchlistRow = {
  id: number;
  symbol: string;
  company: string | null;
};

export type CategoryBucket = "promoter" | "fii" | "dii" | "public" | "other";

export type CategoryHoldingRow = {
  id: number;
  symbol: string;
  company: string;
  category_bucket: CategoryBucket;
  category_raw: string | null;
  pct: number;
  shares: number;
  prev_pct: number | null;
  quarter_end: string;
  status: "new" | "added" | "sold" | "existing";
};
