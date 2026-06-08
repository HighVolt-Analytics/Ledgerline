export default function SectionTitle({ children, className = '' }) {
  return (
    <h2 className={`text-4xl font-medium tracking-[-0.03em] text-foreground md:text-5xl ${className}`}>
      {children}
    </h2>
  );
}
