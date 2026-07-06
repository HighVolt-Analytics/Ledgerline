import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type SkeletonProps = HTMLAttributes<HTMLDivElement> & {
  circle?: boolean;
  pill?: boolean;
};

export function Skeleton({ className, circle, pill, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        "skeleton",
        circle && "skeleton--circle",
        pill && "skeleton--pill",
        className
      )}
      aria-hidden
      {...props}
    />
  );
}
