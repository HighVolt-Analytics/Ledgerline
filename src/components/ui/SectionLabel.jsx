export default function SectionLabel({ children }) {
  return (
    <p className="font-mono text-[12px] uppercase tracking-[0.28em] text-muted-foreground">
      {children}
    </p>
  );
}
