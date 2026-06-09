import { useMemo } from "react";
import { fmtAud } from "@/lib/v4MockData";

export function ReceiptThumb({
  merchant,
  date,
  amount,
  gst,
}: {
  merchant: string;
  date: string;
  amount: number;
  gst: number;
}) {
  const ref = useMemo(
    () => Math.floor((merchant.length * 997 + amount) % 9000) + 1000,
    [merchant, amount]
  );
  return (
    <div
      className="mx-auto w-full max-w-[260px] rounded-md bg-white text-slate-800 shadow-sm border border-slate-200 font-mono text-[11px] leading-relaxed"
      style={{
        clipPath:
          "polygon(0 0,100% 0,100% 97%,96% 100%,92% 97%,88% 100%,84% 97%,80% 100%,76% 97%,72% 100%,68% 97%,64% 100%,60% 97%,56% 100%,52% 97%,48% 100%,44% 97%,40% 100%,36% 97%,32% 100%,28% 97%,24% 100%,20% 97%,16% 100%,12% 97%,8% 100%,4% 97%,0 100%)",
      }}
    >
      <div className="px-4 pt-4 pb-6">
        <div className="text-center font-bold tracking-wide uppercase text-[12px]">{merchant}</div>
        <div className="text-center text-slate-400 mb-3">TAX INVOICE</div>
        <div className="flex justify-between">
          <span>Date</span>
          <span>{date}</span>
        </div>
        <div className="flex justify-between">
          <span>Ref</span>
          <span>#{ref}</span>
        </div>
        <div className="border-t border-dashed border-slate-300 my-2" />
        <div className="flex justify-between">
          <span>Subtotal</span>
          <span>{fmtAud(amount - gst)}</span>
        </div>
        <div className="flex justify-between">
          <span>GST</span>
          <span>{fmtAud(gst)}</span>
        </div>
        <div className="border-t border-dashed border-slate-300 my-2" />
        <div className="flex justify-between font-bold text-[12px]">
          <span>TOTAL</span>
          <span>{fmtAud(amount)}</span>
        </div>
      </div>
    </div>
  );
}
