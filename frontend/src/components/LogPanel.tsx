import { useEffect, useRef, useState } from "react";

// usb-proxy can print thousands of lines a second. Keep a bounded tail.
const MAX_LINES = 2000;

interface Props {
  title?: string;
  // A server-sent-events endpoint that sends JSON arrays of lines.
  url?: string;
  empty?: string;
}

export function LogPanel({ title = "Log", url = "/api/logs", empty = "No log lines yet." }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [follow, setFollow] = useState(true);
  const [connected, setConnected] = useState(false);
  const box = useRef<HTMLPreElement>(null);

  useEffect(() => {
    // EventSource reconnects by itself, and sends the session cookie.
    const source = new EventSource(url);
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
  }, [url]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, follow]);

  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        <span className={connected ? "dot ok" : "dot"} title={connected ? "Live" : "Reconnecting"} />
        <span className="spacer" />
        <label className="check inline">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          <span>Follow</span>
        </label>
        <button className="quiet" onClick={() => setLines([])}>Clear</button>
      </div>
      <pre className="log" ref={box}>
        {lines.length ? lines.join("\n") : empty}
      </pre>
    </section>
  );
}
