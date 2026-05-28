import type { InputHTMLAttributes } from "react";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return (
    <input
      {...rest}
      className={
        "block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm " +
        "focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none " +
        className
      }
    />
  );
}

export function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block mb-3">
      <div className="text-xs font-medium text-gray-700 mb-1">{label}</div>
      {children}
      {hint && <div className="text-xs text-gray-500 mt-1">{hint}</div>}
    </label>
  );
}
