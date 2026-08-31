import { cn } from "@/lib/cn";

export function BankFeedOkButton({
  disabled,
  busy,
  onClick,
}: {
  disabled: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={onClick}
      data-testid="bf-ok-button"
      className={cn(
        "inline-flex h-[34px] min-w-[52px] items-center justify-center rounded-sm px-4 text-sm font-semibold text-white",
        "bg-[#008abf] shadow-sm transition-colors hover:bg-[#007aa3]",
        "disabled:cursor-not-allowed disabled:bg-[#b0bcc4] disabled:text-white/90 disabled:shadow-none"
      )}
    >
      OK
    </button>
  );
}
