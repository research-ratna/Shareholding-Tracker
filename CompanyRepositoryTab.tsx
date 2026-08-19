"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase, CategoryHoldingRow, CategoryBucket } from "@/lib/supabaseClient";

const BUCKETS: { key: CategoryBucket; label: string }[] = [
  { key: "promoter", label: "Promoter" },
  { key: "fii", label: "FII" },
  { key: "dii", label: "DII" },
  { key: "public", label: "Public" },
  { key: "other", label: "Other" },
];

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

type Group = { symbol: string; company: string; quarter_end: string; byBucket: Partial<Record<CategoryBucket, CategoryHoldingRow>> };

export default function CompanyRepositoryTab() {
  const [rows, setRows] = useState<CategoryHoldingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [quarterFilter, setQuarterFilter] = useState("");

  useEffect(() => {
    supabase
      .from("sht_category_holdings")
      .select("*")
      .order("quarter_end", { ascending: false })
      .then(({ data }) => {
        if (data) setRows(data as CategoryHoldingRow[]);
        setLoading(false);
      });
  }, []);

  const quarters = useMemo(() => {
    const set = new Set(rows.map((r) => r.quarter_end));
    return Array.from(set).sort().reverse();
  }, [rows]);

  const groups = useMemo<Group[]>(() => {
    const q = search.toLowerCase();
    const map = new Map<string, Group>();
    for (const r of rows) {
      if (quarterFilter && r.quarter_end !== quarterFilter) continue;
      if (q && !r.company.toLowerCase().includes(q) && !r.symbol.toLowerCase().includes(q)) continue;
      const key = `${r.symbol}|${r.quarter_end}`;
      if (!map.has(key)) map.set(key, { symbol: r.symbol, company: r.company, quarter_end: r.quarter_end, byBucket: {} });
      map.get(key)!.byBucket[r.category_bucket] = r;
    }
    return Array.from(map.values()).sort(
      (a, b) => b.quarter_end.localeCompare(a.quarter_end) || a.company.localeCompare(b.company)
    );
  }, [rows, search, quarterFilter]);

  function resetFilters() {
    setSearch("");
    setQuarterFilter("");
  }

  return (
    <div>
      <div className="note">
        One row per company per quarter. Select a quarter below to see a snapshot, or leave it on "All
        quarters" to see the full history for each company, most recent first.
      </div>
      <div className="card">
        <div className="filters">
          <input
            type="text"
            placeholder="Search company or symbol"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={quarterFilter} onChange={(e) => setQuarterFilter(e.target.value)}>
            <option value="">All quarters</option>
            {quarters.map((q) => (
              <option key={q} value={q}>
                {formatDate(q)}
              </option>
            ))}
          </select>
          <button className="btn" onClick={resetFilters}>
            Reset
          </button>
        </div>
        <p className="count">{loading ? "Loading…" : `${groups.length} compan${groups.length === 1 ? "y" : "ies"}-quarter row(s)`}</p>
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Quarter</th>
              {BUCKETS.map((b) => (
                <th key={b.key} className="bucket-cell">{b.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={`${g.symbol}|${g.quarter_end}`}>
                <td>
                  {g.company}
                  <span style={{ color: "var(--text-mute)", marginLeft: 6 }} className="mono">{g.symbol}</span>
                </td>
                <td className="mono" style={{ color: "var(--text-2)" }}>{formatDate(g.quarter_end)}</td>
                {BUCKETS.map((b) => {
                  const r = g.byBucket[b.key];
                  if (!r) return <td key={b.key} className="bucket-cell mono" style={{ color: "var(--text-mute)" }}>—</td>;
                  const delta = r.prev_pct !== null ? Number(r.pct) - Number(r.prev_pct) : null;
                  const dir = delta === null ? "flat" : delta > 0.05 ? "up" : delta < -0.05 ? "down" : "flat";
                  return (
                    <td key={b.key} className="bucket-cell mono">
                      <span className="bucket-pct">{Number(r.pct).toFixed(2)}%</span>
                      {delta !== null && Math.abs(delta) > 0.05 && (
                        <span className={`bucket-delta ${dir}`}>
                          {dir === "up" ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}pp
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
