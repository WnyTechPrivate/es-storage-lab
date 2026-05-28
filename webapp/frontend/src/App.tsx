import { Link, NavLink, Route, Routes } from "react-router-dom";
import { Wizard } from "./pages/Wizard";
import { Reports } from "./pages/Reports";
import { RunDetail } from "./pages/RunDetail";
import { Cleanup } from "./pages/Cleanup";

export default function App() {
  return (
    <div className="min-h-full">
      <header className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-3 flex items-center gap-4">
          <Link to="/" className="font-semibold text-gray-800">
            ES Storage Lab
          </Link>
          <nav className="ml-4 flex gap-1 text-sm">
            <NavTab to="/">New run</NavTab>
            <NavTab to="/reports">Reports</NavTab>
            <NavTab to="/cleanup">Cleanup</NavTab>
          </nav>
          <div className="ml-auto text-xs text-gray-400">v0.1 · M1</div>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Wizard />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/report/:id" element={<RunDetail />} />
          <Route path="/cleanup" element={<Cleanup />} />
        </Routes>
      </main>
    </div>
  );
}

function NavTab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        "px-3 py-1.5 rounded-md " +
        (isActive ? "bg-brand-50 text-brand-700" : "text-gray-600 hover:bg-gray-50")
      }
    >
      {children}
    </NavLink>
  );
}
