import { useEffect, useRef, useState } from "react";

// usb-proxy can print thousands of lines a second. Keep a bounded tail.
const MAX_LINES = 2000;

export function LogPanel() {
  const [lines, setLines] = useState<string[]>([]);
  const [follow, setFollow] = useState(true);
  const [connected, setConnected] = useState(false);
  const box = useRef<HTMLPreElement>(null);

  useEffect(() => {
    // EventSource reconnects by itself, and sends the session cookie.
    const source = new EventSource("/api/logs");
    source.onopen = () => {
      setConnected(true);
      // Each connection replays the recent journal, so start clean.
      setLines([]);
    };
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      const batch = JSON.parse(event.data) as string[];
      setLines((old) => [...old, ...batch].slice(-MAX_LINES));
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, follow]);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Log</h2>
        <span className={connected ? "dot ok" : "dot"} title={connected ? "Live" : "Reconnecting"} />
        <span className="spacer" />
        <label className="check inline">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          <span>Follow</span>
        </label>
        <button className="quiet" onClick={() => setLines([])}>Clear</button>
      </div>
      <pre className="log" ref={box}>
        {lines.length ? lines.join("\n") : "No log lines yet."}
      </pre>
    </section>
  );
}
