import { cn } from "@/lib/cn";

export function Badge({
  className,
  variant = "outline",
  children,
  title,
}: {
  className?: string;
  variant?: "default" | "outline" | "secondary" | "destructive";
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <div
      className={cn(
        "badge whitespace-nowrap inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors hover-elevate",
        variant === "default" && "border-transparent bg-primary text-primary-foreground shadow-xs",
        variant === "secondary" &&
          "border-transparent bg-secondary text-secondary-foreground",
        variant === "destructive" &&
          "border-transparent bg-destructive text-destructive-foreground",
        variant === "outline" && "border [border-color:var(--badge-outline)] shadow-xs",
        className
      )}
      title={title}
    >
      {children}
    </div>
  );
}
