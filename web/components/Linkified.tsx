export function Linkified({ text }: { text: string }) {
  return <>{text.split(/(https:\/\/\S+)/g).map((p, i) => /^https:\/\//.test(p)
    ? <a key={i} href={p} target="_blank" rel="noopener" className="link">Open payment link</a> : p)}</>;
}
