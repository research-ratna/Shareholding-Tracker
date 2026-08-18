"use client";

import { useState } from "react";
import InputTab from "@/components/InputTab";
import RepositoryTab from "@/components/RepositoryTab";

export default function Page() {
  const [tab, setTab] = useState<"input" | "repo">("input");

  return (
    <div className="wrap">
      <h1>Shareholding tracker</h1>
      <p className="sub">Quarterly ≥1% filings for the investors and entities you're watching.</p>

      <div className="tabs">
        <button className={`tab ${tab === "input" ? "active" : ""}`} onClick={() => setTab("input")}>
          Input
        </button>
        <button className={`tab ${tab === "repo" ? "active" : ""}`} onClick={() => setTab("repo")}>
          Data repository
        </button>
      </div>

      {tab === "input" ? <InputTab /> : <RepositoryTab />}
    </div>
  );
}
