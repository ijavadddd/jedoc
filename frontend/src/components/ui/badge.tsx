import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      outline: "border-border text-muted-foreground",
      ask: "border-sky/40 text-sky",
      do: "border-gold/50 text-gold",
    },
  },
  defaultVariants: { variant: "outline" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
