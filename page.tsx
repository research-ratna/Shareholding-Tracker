"use client";

import { useState } from "react";
import InputTab from "@/components/InputTab";
import RepositoryTab from "@/components/RepositoryTab";
import CompanyInputTab from "@/components/CompanyInputTab";
import CompanyRepositoryTab from "@/components/CompanyRepositoryTab";

type Mode = "investors" | "companies";

export default function Page() {
  const [mode, setMode] = useState<Mode>("investors");
  const [tab, setTab] = useState<"input" | "repo">("input");

  return (
    <div className="wrap">
      <h1>Shareholding tracker</h1>
      <p className="sub">
        {mode === "investors"
          ? "Quarterly ≥1% filings for the investors and entities you're watching."
          : "Quarterly Promoter / FII / DII / Public movement for the companies you're watching."}
      </p>

      <div className="mode-switch">
        <button className={`mode-btn ${mode === "investors" ? "active" : ""}`} onClick={() => setMode("investors")}>
          Investors → Companies
        </button>
        <button className={`mode-btn ${mode === "companies" ? "active" : ""}`} onClick={() => setMode("companies")}>
          Companies → Ownership
        </button>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === "input" ? "active" : ""}`} onClick={() => setTab("input")}>
          Input
        </button>
        <button className={`tab ${tab === "repo" ? "active" : ""}`} onClick={() => setTab("repo")}>
          Data repository
        </button>
      </div>

      {mode === "investors" ? (
        tab === "input" ? <InputTab /> : <RepositoryTab />
      ) : tab === "input" ? (
        <CompanyInputTab />
      ) : (
        <CompanyRepositoryTab />
      )}
    </div>
  );
}
