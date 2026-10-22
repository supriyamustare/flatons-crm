import { useEffect, useState } from "react";

type Health = { status: string; database: string; redis: string };
type State = { kind: "loading" } | { kind: "ready"; data: Health } | { kind: "unreachable" };

const LABELS: Record<string, string> = { database: "Database", redis: "Task queue" };

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json() as Promise<Health>)
      .then((data) => setState({ kind: "ready", data }))
      .catch(() => setState({ kind: "unreachable" }));
  }, []);

  return (
    <main className="shell">
      <div className="mark" aria-hidden="true">F</div>
      <h1>Flatons CRM</h1>
      <p className="lede">The server is set up. The sales workspace arrives in the first sprint.</p>

      <section className="status" aria-live="polite">
        {state.kind === "loading" && <p>Checking the server…</p>}
        {state.kind === "unreachable" && (
          <p className="bad">The API isn’t responding. Check that flatons-api is running.</p>
        )}
        {state.kind === "ready" && (
          <ul>
            {(["database", "redis"] as const).map((key) => (
              <li key={key}>
                <span>{LABELS[key]}</span>
                <span className={state.data[key] === "ok" ? "ok" : "bad"}>
                  {state.data[key] === "ok" ? "Connected" : "Not reachable"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
