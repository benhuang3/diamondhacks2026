import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-slate-200 bg-slate-100 text-slate-800",
        high: "border-rose-200 bg-rose-100 text-rose-800",
        medium: "border-amber-200 bg-amber-100 text-amber-800",
        low: "border-sky-200 bg-sky-100 text-sky-800",
        outline: "border-slate-300 bg-transparent text-slate-700",
        success: "border-emerald-200 bg-emerald-100 text-emerald-800",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}
