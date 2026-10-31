"use client";
import { useEffect, useRef } from "react";

/**
 * Subscribe to /api/stream/{channel}. `since` resumes after that event id (use RunDetail.last_event_id
 * so a snapshot plus the stream has no gap); EventSource reconnects on its own and resends Last-Event-ID.
 */
export function useStream(
  channel: string | null,
  events: string[],
  onEvent: (name: string, data: any) => void,
  since?: number,
) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const names = events.join(",");

  useEffect(() => {
    if (!channel || since === undefined) return;
    const url = `/api/stream/${encodeURIComponent(channel)}?since=${since}`;
    const es = new EventSource(url);
    for (const name of names.split(",")) {
      es.addEventListener(name, (e) => handler.current(name, JSON.parse((e as MessageEvent).data)));
    }
    return () => es.close();
  }, [channel, names, since]);
}
