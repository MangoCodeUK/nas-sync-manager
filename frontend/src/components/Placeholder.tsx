// Temporary page body shown until a feature stage fills it in.
export function Placeholder({ title, stage }: { title: string; stage: number }) {
  return (
    <div className="page">
      <h1>{title}</h1>
      {stage > 0 ? (
        <p className="muted">This page arrives in build Stage {stage}.</p>
      ) : (
        <p className="muted">Nothing here.</p>
      )}
    </div>
  );
}
