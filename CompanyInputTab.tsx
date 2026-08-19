"use client";

import { useEffect, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { supabase, CompanyWatchlistRow } from "@/lib/supabaseClient";

export default function CompanyInputTab() {
  const [companies, setCompanies] = useState<CompanyWatchlistRow[]>([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadAll() {
    setLoading(true);
    const { data } = await supabase
      .from("sht_company_watchlist")
      .select("id, symbol, company")
      .order("symbol");
    if (data) setCompanies(data as CompanyWatchlistRow[]);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function addRow() {
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;
    setFormError(null);
    const { data, error } = await supabase
      .from("sht_company_watchlist")
      .insert({ symbol })
      .select()
      .single();
    if (error) {
      setFormError(error.code === "23505" ? `${symbol} is already on your watchlist.` : `Could not add row: ${error.message}`);
      return;
    }
    if (data) {
      setCompanies((c) => [...c, data as CompanyWatchlistRow].sort((a, b) => a.symbol.localeCompare(b.symbol)));
      setNewSymbol("");
    }
  }

  async function deleteRow(id: number) {
    setCompanies((c) => c.filter((r) => r.id !== id));
    await supabase.from("sht_company_watchlist").delete().eq("id", id);
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
          const symKey = keys.find((k) => /symbol|ticker|nse/i.test(k)) ?? keys[0];
          return { symbol: String(r[symKey] ?? "").trim().toUpperCase() };
        })
        .filter((r) => r.symbol);

      if (parsed.length === 0) {
        setFormError(
          rows.length === 0
            ? "That file has no rows."
            : `Read ${rows.length} row(s) but none had a symbol value. Check the header row has a column matching "symbol" (case doesn't matter).`
        );
        return;
      }

      const seen = new Set<string>();
      const deduped = parsed.filter((r) => (seen.has(r.symbol) ? false : (seen.add(r.symbol), true)));

      // Same safe-replace pattern as the investor watchlist: upsert the new
      // list first, only remove what's no longer in the file after that
      // succeeds, so a failed import never leaves you with an empty list.
      const { data: kept, error: upsertError } = await supabase
        .from("sht_company_watchlist")
        .upsert(deduped, { onConflict: "symbol" })
        .select();

      if (upsertError) {
        setFormError(`Import failed, your existing watchlist was left untouched: ${upsertError.message}`);
        return;
      }

      const keepIds = (kept ?? []).map((r) => r.id);
      if (keepIds.length > 0) {
        const { error: deleteError } = await supabase
          .from("sht_company_watchlist")
          .delete()
          .not("id", "in", `(${keepIds.join(",")})`);
        if (deleteError) {
          setFormError(`Imported ${keepIds.length} row(s), but couldn't clear rows removed from the file: ${deleteError.message}`);
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
    const ws = XLSX.utils.json_to_sheet(companies.map((c) => ({ symbol: c.symbol, company: c.company ?? "" })));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Companies");
    XLSX.writeFile(wb, "company-watchlist.xlsx");
  }

  return (
    <div>
      <div className="card">
        <h2>Upload from Excel</h2>
        <p className="hint">
          Column "symbol" (the NSE trading symbol, e.g. RELIANCE, TCS, INFY), one row per company. Uploading
          replaces the current list.
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
        <h2>Your company watchlist</h2>
        <p className="hint">
          Enter the NSE trading symbol directly - the scraper fills in the company name the first time it
          fetches that symbol.
        </p>
        {loading ? (
          <p className="hint">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Symbol</th>
                <th>Company</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {companies.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.symbol}</td>
                  <td style={{ color: row.company ? "var(--text)" : "var(--text-mute)" }}>
                    {row.company ?? "not fetched yet"}
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
            placeholder="NSE symbol, e.g. RELIANCE"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addRow()}
          />
          <button className="btn primary" onClick={addRow}>
            Add symbol
          </button>
          <button className="btn" onClick={exportXlsx}>
            Download list (.xlsx)
          </button>
        </div>
      </div>
    </div>
  );
}
