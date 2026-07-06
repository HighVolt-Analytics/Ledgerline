import { Search } from "lucide-react";
import { cn } from "@/lib/cn";

type ListSearchInputProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  testId?: string;
  className?: string;
};

export function ListSearchInput({
  value,
  onChange,
  placeholder = "Search…",
  testId,
  className,
}: ListSearchInputProps) {
  return (
    <div className={cn("relative", className)}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-testid={testId}
        aria-label={placeholder}
        className="h-8 w-full min-w-[12rem] max-w-xs rounded-md border border-border bg-field pl-8 pr-3 text-xs outline-none focus:border-primary/40"
      />
    </div>
  );
}
