import { highlight } from "../../lib/highlight";

/** codeRows (line 2015): numbered, highlighted source rows, shared by the vault preview and the reader. */
export function CodeRows({ lines }: { lines: string[] }) {
  return (
    <>
      {highlight(lines).map((h, i) => (
        <div key={i} className="code-row">
          <span className="ln">{i + 1}</span>
          <span className="tx" dangerouslySetInnerHTML={{ __html: h || " " }} />
        </div>
      ))}
    </>
  );
}
