import type { ComponentProps, ReactNode } from "react"
import { cva } from "class-variance-authority"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import { Slot } from "@radix-ui/react-slot"

// shadcn/ui primitives adapted to the dashboard theme.
const buttonVariants = cva("button [&_svg]:pointer-events-none [&_svg]:shrink-0", {
  variants:{variant:{primary:"primary",secondary:"secondary",ghost:"ghost"}},
  defaultVariants:{variant:"secondary"},
})
export function Button({variant="secondary",className,type="button",asChild=false,...props}:
  ComponentProps<"button"> & {variant?:"primary"|"secondary"|"ghost";asChild?:boolean}) {
  const Component = asChild ? Slot : "button"
  return <Component data-slot="button" data-variant={variant} type={asChild ? undefined : type}
    className={twMerge(clsx(buttonVariants({variant}),className))} {...props}/>
}
export function Card({className,...props}:ComponentProps<"section">) {
  return <section data-slot="card" className={twMerge(clsx("card",className))} {...props}/>
}
export function Badge({children,tone="neutral"}:{children:ReactNode;tone?:string}) {
  return <span data-slot="badge" className={`badge ${tone}`}>{children}</span>
}
export function Field({label,children}:{label:string;children:ReactNode}) {
  return <label className="field"><span>{label}</span>{children}</label>
}
export function Check({label,checked,change}:{label:string;checked:boolean;change:(value:boolean)=>void}) {
  return <label className="check"><input type="checkbox" checked={checked} onChange={e=>change(e.target.checked)}/>{label}</label>
}
