"use client";

import { useEffect } from "react";
import ReportPage from "../page";

/** Print view: renders the full report, then opens the browser's print dialog (choose "Save as PDF"). */
export default function PrintReport({ params }: { params: Promise<{ id: string }> }) {

  useEffect(() => {
    // Wait for the report (and its images) to load before printing.
    const t = setInterval(() => {
      if (document.querySelector("main h1") && !document.body.textContent?.includes("Loading report")) {
        clearInterval(t);
        setTimeout(() => window.print(), 1200);
      }
    }, 500);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <div className="no-print mx-auto flex max-w-6xl items-center justify-between gap-3 px-5 pt-6">
        <p className="text-sm text-muted">In the print window, choose <b>Save as PDF</b> as the destination.</p>
        <button onClick={() => window.print()} className="btn-secondary">Save as PDF</button>
      </div>
      <ReportPage params={params} />
    </>
  );
}
