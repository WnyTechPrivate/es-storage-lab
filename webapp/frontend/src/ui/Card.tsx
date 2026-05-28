import type { ReactNode } from "react";

export function Card({ title, children, footer }: {
  title?: ReactNode; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <div className="rounded-xl bg-white border border-gray-200 shadow-sm">
      {title && (
        <div className="px-5 py-3 border-b border-gray-100 text-sm font-semibold text-gray-800">
          {title}
        </div>
      )}
      <div className="p-5">{children}</div>
      {footer && (
        <div className="px-5 py-3 border-t border-gray-100 bg-gray-50 rounded-b-xl flex items-center justify-end gap-2">
          {footer}
        </div>
      )}
    </div>
  );
}
