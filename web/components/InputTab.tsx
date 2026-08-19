"use client";

import { useEffect, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { supabase, WatchlistRow, ReviewRow } from "@/lib/supabaseClient";

export default function InputTab() {
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewRow[]>([]);
  const [newInvestor, setNewInvestor] = useState("");
  const [newEntity, setNewEntity] = useState("");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadAll() {
    setLoading(true);
    const [wl, rv] = await Promise.all([
      supabase.from("sht_watchlist_entities").select("id, investor, entity").order("investor"),
      supabase.from("sht_review_queue").select("*").eq("resolved", false).order("created_at", { ascending: false }),
    ]);
    if (wl.data) setWatchlist(wl.data as WatchlistRow[]);
    if (rv.data) setReviewItems(rv.data as ReviewRow[]);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function addRow() {
    const investor = newInvestor.trim();
    const entity = newEntity.trim();
    if (!investor || !entity) return;
    setFormError(null);
    const { data, error } = await supabase
      .from("sht_watchlist_entities")
      .insert({ investor, entity })
      .select()
      .single();
    if (error) {
      setFormError(
        error.code === "23505"
          ? `"${investor}" via "${entity}" is already on your watchlist.`
          : `Could not add row: ${error.message}`
      );
      return;
    }
    if (data) {
      setWatchlist((w) => [...w, data as WatchlistRow]);
      setNewInvestor("");
      setNewEntity("");
    }
  }

  async function updateRow(id: number, field: "investor" | "entity", value: string) {
    setWatchlist((w) => w.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
    await supabase.from("sht_watchlist_entities").update({ [field]: value }).eq("id", id);
  }

  async function deleteRow(id: number) {
    setWatchlist((w) => w.filter((r) => r.id !== id));
    await supabase.from("sht_watchlist_entities").delete().eq("id", id);
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFormError(null);
    setImporting(true);
    try {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });
      const sheet = wb.Sheets[wb.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);

      const parsed = rows
        .map((r) => {
          const keys = Object.keys(r);
          const invKey = keys.find((k) => /invest/i.test(k)) ?? keys[0];
          const entKey = keys.find((k) => /entit/i.test(k)) ?? keys[1];
          return {
            investor: String(r[invKey] ?? "").trim(),
            entity: entKey ? String(r[entKey] ?? "").trim() : "",
          };
        })
        .filter((r) => r.investor && r.entity);

      if (parsed.length === 0) {
        setFormError(
          rows.length === 0
            ? "That file has no rows."
            : `Read ${rows.length} row(s) but none had both an investor and an entity value. Check the header row has columns matching "investor" and "entity" (case doesn't matter).`
        );
        return;
      }

      // De-dupe exact investor+entity pairs within the file itself - the
      // table has a unique constraint on (investor, entity), so duplicate
      // rows in the source file would otherwise abort the whole write.
      const seen = new Set<string>();
      const deduped = parsed.filter((r) => {
        const k = `${r.investor.toLowerCase()}|${r.entity.toLowerCase()}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });

      // Upsert (not delete-then-insert): rows unchanged from before just
      // get re-affirmed, so we never touch the table until we know the
      // new list is good. Old rows that are no longer in the file get
      // removed in a second step, once we have the confirmed keep-list.
      const { data: kept, error: upsertError } = await supabase
        .from("sht_watchlist_entities")
        .upsert(deduped, { onConflict: "investor,entity" })
        .select();

      if (upsertError) {
        setFormError(`Import failed, your existing watchlist was left untouched: ${upsertError.message}`);
        return;
      }

      const keepIds = (kept ?? []).map((r) => r.id);
      if (keepIds.length > 0) {
        const { error: deleteError } = await supabase
          .from("sht_watchlist_entities")
          .delete()
          .not("id", "in", `(${keepIds.join(",")})`);
        if (deleteError) {
          setFormError(
            `Imported ${keepIds.length} row(s), but couldn't clear rows that were removed from the file: ${deleteError.message}`
          );
        }
      }

      await loadAll();
    } catch (err) {
      setFormError(err instanceof Error ? `Could not read that file: ${err.message}` : "Could not read that file.");
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function exportXlsx() {
    const ws = XLSX.utils.json_to_sheet(watchlist.map((w) => ({ investor: w.investor, entity: w.entity })));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Watchlist");
    XLSX.writeFile(wb, "investor-watchlist.xlsx");
  }

  async function confirmReview(item: ReviewRow) {
    if (!item.candidate_watchlist_id) return;
    const entity = watchlist.find((w) => w.id === item.candidate_watchlist_id);
    if (!entity) return;

    // Look up the previous quarter's pct for this exact entity+symbol so
    // the confirmed row gets a correct new/added/sold/existing status,
    // same rule the scraper itself uses.
    const { data: prevRows } = await supabase
      .from("sht_holdings")
      .select("pct, quarter_end")
      .eq("symbol", item.symbol)
      .eq("entity", entity.entity)
      .lt("quarter_end", item.quarter_end)
      .order("quarter_end", { ascending: false })
      .limit(1);

    const prevPct = prevRows && prevRows.length > 0 ? Number(prevRows[0].pct) : null;
    const delta = item.pct !== null ? item.pct - (prevPct ?? item.pct) : 0;
    const status = prevPct === null ? "new" : delta > 0.05 ? "added" : delta < -0.05 ? "sold" : "existing";

    await supabase.from("sht_holdings").upsert(
      {
        symbol: item.symbol,
        company: item.company,
        entity: entity.entity,
        investor: entity.investor,
        watchlist_id: entity.id,
        category: item.category,
        pct: item.pct,
        shares: item.shares,
        prev_pct: prevPct,
        quarter_end: item.quarter_end,
        status,
      },
      { onConflict: "symbol,entity,quarter_end" }
    );
    await supabase.from("sht_review_queue").update({ resolved: true }).eq("id", item.id);
    setReviewItems((r) => r.filter((x) => x.id !== item.id));
  }

  async function rejectReview(item: ReviewRow) {
    await supabase.from("sht_review_queue").update({ resolved: true }).eq("id", item.id);
    setReviewItems((r) => r.filter((x) => x.id !== item.id));
  }

  return (
    <div>
      <div className="card">
        <h2>Upload from Excel</h2>
        <p className="hint">
          Columns "investor" and "entity", one row per entity. Uploading replaces the current list.
        </p>
        <label className="drop">
          <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleFile} disabled={importing} />
          {importing ? "Importing…" : "Click to choose an .xlsx or .csv file"}
        </label>
      </div>

      {formError && (
        <div className="card" style={{ borderColor: "#c0392b" }}>
          <p className="hint" style={{ color: "#c0392b" }}>{formError}</p>
        </div>
      )}

      <div className="card">
        <h2>Your watchlist</h2>
        <p className="hint">Click any cell to edit it directly, or add a row below.</p>
        {loading ? (
          <p className="hint">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: "38%" }}>Investor</th>
                <th>Entity they invest through</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {watchlist.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="text"
                      value={row.investor}
                      onChange={(e) => updateRow(row.id, "investor", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      value={row.entity}
                      onChange={(e) => updateRow(row.id, "entity", e.target.value)}
                    />
                  </td>
                  <td>
                    <button className="del" title="Remove" onClick={() => deleteRow(row.id)}>
                      &times;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row-form">
          <input
            type="text"
            placeholder="Investor name"
            value={newInvestor}
            onChange={(e) => setNewInvestor(e.target.value)}
          />
          <input
            type="text"
            placeholder="Entity name"
            value={newEntity}
            onChange={(e) => setNewEntity(e.target.value)}
          />
          <button className="btn primary" onClick={addRow}>
            Add row
          </button>
          <button className="btn" onClick={exportXlsx}>
            Download list (.xlsx)
          </button>
        </div>
      </div>

      {reviewItems.length > 0 && (
        <div className="card">
          <h2>Needs review</h2>
          <p className="hint">
            Names close to something on your watchlist, but not exact. Confirm to log it as a real
            holding, or reject if it's a different person or entity.
          </p>
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Filed name</th>
                <th>Closest match</th>
                <th>Similarity</th>
                <th style={{ width: 150 }}></th>
              </tr>
            </thead>
            <tbody>
              {reviewItems.map((item) => {
                const candidate = watchlist.find((w) => w.id === item.candidate_watchlist_id);
                return (
                  <tr key={item.id}>
                    <td>{item.company}</td>
                    <td>{item.raw_holder_name}</td>
                    <td style={{ color: "var(--text-2)" }}>{candidate ? `${candidate.investor} — ${candidate.entity}` : "—"}</td>
                    <td className="mono">{item.similarity?.toFixed(0)}%</td>
                    <td>
                      <button className="btn primary" style={{ marginRight: 6 }} onClick={() => confirmReview(item)}>
                        Confirm
                      </button>
                      <button className="btn" onClick={() => rejectReview(item)}>
                        Reject
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

