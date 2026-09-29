import { useEffect, useState } from "react";

import { applyScreenHeight, diagnosticsOpen, report, setDiagnosticsOpen } from "../pwa/diagnostics";

/**
 * About → "Display diagnostics": the screen's measurements, coloured lines at the bottom
 * of the window (red), the app (blue) and the screen (green).
 */
export function DisplayDiagnostics() {
  const [open, setOpen] = useState(diagnosticsOpen);
  const [lines, setLines] = useState<[string, string][]>([]);
  const [folded, setFolded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onToggle = () => setOpen(diagnosticsOpen());
    window.addEventListener("sb-diagnostics", onToggle);
    return () => window.removeEventListener("sb-diagnostics", onToggle);
  }, []);

  useEffect(() => {
    if (!open) return;
    document.documentElement.dataset.diagnostics = "";
    const refresh = () => {
      applyScreenHeight();
      setLines(report());
    };
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => {
      window.clearInterval(timer);
      delete document.documentElement.dataset.diagnostics;
    };
  }, [open]);

  if (!open) return null;

  async function copy() {
    const text = lines.map(([label, value]) => `${label}: ${value}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <>
      <div className="diagnostics-line diagnostics-line--window" aria-hidden="true" />
      <div className="diagnostics-line diagnostics-line--screen" aria-hidden="true" />
      <section className={`diagnostics${folded ? " diagnostics--folded" : ""}`} aria-label="Display diagnostics">
        <div className="diagnostics__bar">
          <strong>Display diagnostics</strong>
          <button className="diagnostics__button" type="button" onClick={() => setFolded(!folded)}>
            {folded ? "Show" : "Fold"}
          </button>
          <button className="diagnostics__button" type="button" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button className="diagnostics__button" type="button" onClick={() => setDiagnosticsOpen(false)}>
            Close
          </button>
        </div>
        {!folded && (
          <>
            <p className="diagnostics__legend">
              Lines at the bottom: <span className="diagnostics__red">red</span> = window,{" "}
              <span className="diagnostics__blue">blue</span> = app, <span className="diagnostics__green">green</span> =
              screen height.
            </p>
            <dl className="diagnostics__values">
              {lines.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </section>
    </>
  );
}
