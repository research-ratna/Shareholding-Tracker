"use client";

import { useEffect, useMemo, useState, Fragment } from "react";
import { supabase, HoldingRow } from "@/lib/supabaseClient";

const statusLabel: Record<HoldingRow["status"], string> = {
  new: "New entry",
  added: "Added",
  sold: "Sold",
  existing: "Existing stake",
};

function formatIN(num: number): string {
  const s = Math.round(num).toString();
  if (s.length <= 3) return s;
  const last3 = s.slice(-3);
  const rest = s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return rest + "," + last3;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

type Group = { key: string; rows: HoldingRow[] };

export default function RepositoryTab() {
  const [holdings, setHoldings] = useState<HoldingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [quarterFilter, setQuarterFilter] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    supabase
      .from("sht_holdings")
      .select("*")
      .order("quarter_end", { ascending: false })
      .then(({ data }) => {
        if (data) setHoldings(data as HoldingRow[]);
        setLoading(false);
      });
  }, []);

  const quarters = useMemo(() => {
    const set = new Set(holdings.map((h) => h.quarter_end));
    return Array.from(set).sort().reverse();
  }, [holdings]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return holdings.filter(
      (h) =>
        (!q ||
          h.company.toLowerCase().includes(q) ||
          (h.investor ?? "").toLowerCase().includes(q) ||
          h.entity.toLowerCase().includes(q)) &&
        (!statusFilter || h.status === statusFilter) &&
        (!quarterFilter || h.quarter_end === quarterFilter)
    );
  }, [holdings, search, statusFilter, quarterFilter]);

  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, HoldingRow[]>();
    for (const r of filtered) {
      const key = `${r.investor}|${r.company}|${r.quarter_end}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    return Array.from(map.entries()).map(([key, rows]) => ({ key, rows }));
  }, [filtered]);

  function toggle(key: string) {
    setExpanded((e) => ({ ...e, [key]: !e[key] }));
  }

  function resetFilters() {
    setSearch("");
    setStatusFilter("");
    setQuarterFilter("");
  }

  return (
    <div>
      <div className="note">
        This grows every quarter as the scraper runs — one row per entity per company per quarter,
        grouped into a combined total wherever one investor holds a company through more than one entity.
      </div>
      <div className="card">
        <h2>Backfill past quarters</h2>
        <p className="hint">
          The daily run only checks the current quarter. To also pick up the last 4 quarters (current +
          3 prior) — useful right after adding new entities to your watchlist — run the backfill workflow
          on GitHub. It can take a while across the full symbol universe; check the Actions tab for progress.
        </p>
        <a
          className="btn primary"
          href="https://github.com/research-ratna/Shareholding-Tracker/actions/workflows/backfill.yml"
          target="_blank"
          rel="noreferrer"
        >
          Open backfill workflow on GitHub ↗
        </a>
      </div>
      <div className="card">
        <div className="filters">
          <input
            type="text"
            placeholder="Search investor, entity or company"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="new">New entry</option>
            <option value="added">Added</option>
            <option value="sold">Sold</option>
            <option value="existing">Existing stake</option>
          </select>
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
        <p className="count">{loading ? "Loading…" : `${filtered.length} of ${holdings.length} records`}</p>
        <p className="hint" style={{ margin: "2px 0 0" }}>
          Rows shaded blue are a combined total across entities — click to expand or collapse.
        </p>
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Investor</th>
              <th>Entity</th>
              <th>Stake</th>
              <th>Shares</th>
              <th>Status</th>
              <th>As of</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              if (g.rows.length === 1) {
                return <EntityRow key={g.key} r={g.rows[0]} sub={false} />;
              }
              const totalPct = g.rows.reduce((s, r) => s + Number(r.pct), 0);
              const totalShares = g.rows.reduce((s, r) => s + Number(r.shares), 0);
              const isOpen = !!expanded[g.key];
              return (
                <Fragment key={g.key}>
                  <tr className="grouprow" onClick={() => toggle(g.key)}>
                    <td>{g.rows[0].company}</td>
                    <td>{g.rows[0].investor}</td>
                    <td style={{ color: "var(--accent)", fontWeight: 500 }}>
                      {isOpen ? "▾" : "▸"} {g.rows.length} entities
                    </td>
                    <td className="mono" style={{ fontWeight: 500 }}>
                      {totalPct.toFixed(2)}%
                    </td>
                    <td className="mono" style={{ fontWeight: 500 }}>
                      {formatIN(totalShares)}
                    </td>
                    <td style={{ color: "var(--text-mute)" }}>—</td>
                    <td className="mono" style={{ color: "var(--text-2)" }}>
                      {formatDate(g.rows[0].quarter_end)}
                    </td>
                  </tr>
                  {isOpen && g.rows.map((r) => <EntityRow key={r.id} r={r} sub />)}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EntityRow({ r, sub }: { r: HoldingRow; sub: boolean }) {
  const showPrior = r.prev_pct !== null && Number(r.prev_pct) !== Number(r.pct);
  return (
    <tr className={sub ? "subrow" : undefined}>
      <td>{sub ? "" : r.company}</td>
      <td>{sub ? "" : r.investor}</td>
      <td style={{ color: "var(--text-2)", paddingLeft: sub ? 28 : undefined }}>{r.entity}</td>
      <td className="mono">
        {Number(r.pct).toFixed(2)}%
        {showPrior && <span className="prior">prev {Number(r.prev_pct).toFixed(2)}%</span>}
      </td>
      <td className="mono">{formatIN(Number(r.shares))}</td>
      <td>
        <span className={`badge ${r.status}`}>{statusLabel[r.status]}</span>
      </td>
      <td className="mono" style={{ color: "var(--text-2)" }}>
        {formatDate(r.quarter_end)}
      </td>
    </tr>
  );
}

