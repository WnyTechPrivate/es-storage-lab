import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300",
  secondary: "bg-white text-gray-800 border border-gray-300 hover:bg-gray-50 disabled:opacity-50",
  ghost: "text-gray-700 hover:bg-gray-100 disabled:opacity-50",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-gray-300",
};

export function Button(
  props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }
) {
  const { variant = "primary", className = "", ...rest } = props;
  return (
    <button
      {...rest}
      className={
        "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors " +
        styles[variant] + " " + className
      }
    />
  );
}
