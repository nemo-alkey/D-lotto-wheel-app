import { useState } from 'react';
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useNavigate } from 'react-router-dom';
import { clearToken, getToken } from './api/client.js';
import Home from './pages/Home.jsx';
import CheckNumbers from './pages/CheckNumbers.jsx';
import Wheels from './pages/Wheels.jsx';
import Backtest from './pages/Backtest.jsx';
import Leaderboard from './pages/Leaderboard.jsx';
import Login from './pages/Login.jsx';

function RequireAuth({ children }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

const linkClass = ({ isActive }) =>
  `flex min-h-[44px] min-w-[44px] items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
    isActive ? 'text-emerald-400' : 'text-neutral-400 hover:text-neutral-200'
  }`;

function Layout() {
  const [moreOpen, setMoreOpen] = useState(false);
  const navigate = useNavigate();

  const logout = () => {
    clearToken();
    navigate('/login', { replace: true });
  };

  return (
    <div className="flex min-h-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
          <h1 className="text-lg font-bold">NZ Lotto</h1>
          {/* Top nav on >=640px */}
          <nav className="hidden items-center gap-1 sm:flex">
            <NavLink to="/" end className={linkClass}>
              Home
            </NavLink>
            <NavLink to="/check" className={linkClass}>
              Check
            </NavLink>
            <NavLink to="/wheels" className={linkClass}>
              Wheels
            </NavLink>
            <NavLink to="/backtest" className={linkClass}>
              Backtest
            </NavLink>
            <NavLink to="/leaderboard" className={linkClass}>
              Leaderboard
            </NavLink>
            <button onClick={logout} className={linkClass({ isActive: false })}>
              Logout
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6 pb-24 sm:pb-6">
        <Outlet />
      </main>

      {/* Bottom nav on mobile */}
      <nav className="fixed bottom-0 left-0 right-0 z-10 border-t border-neutral-800 bg-neutral-950/95 backdrop-blur sm:hidden">
        <div className="mx-auto grid max-w-md grid-cols-4">
          <NavLink to="/" end className={linkClass}>
            Home
          </NavLink>
          <NavLink to="/check" className={linkClass}>
            Check
          </NavLink>
          <NavLink to="/wheels" className={linkClass}>
            Wheels
          </NavLink>
          <div className="relative">
            <button
              onClick={() => setMoreOpen((o) => !o)}
              className={`flex min-h-[44px] min-w-[44px] w-full items-center justify-center px-3 py-2 text-sm font-medium ${
                moreOpen ? 'text-emerald-400' : 'text-neutral-400'
              }`}
            >
              More
            </button>
            {moreOpen && (
              <div className="absolute bottom-full right-0 mb-1 w-44 overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900 shadow-xl">
                <NavLink
                  to="/backtest"
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    `flex min-h-[44px] items-center px-4 text-sm ${
                      isActive ? 'text-emerald-400' : 'text-neutral-300'
                    }`
                  }
                >
                  Backtest
                </NavLink>
                <NavLink
                  to="/leaderboard"
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    `flex min-h-[44px] items-center px-4 text-sm ${
                      isActive ? 'text-emerald-400' : 'text-neutral-300'
                    }`
                  }
                >
                  Leaderboard
                </NavLink>
                <button
                  onClick={logout}
                  className="flex min-h-[44px] w-full items-center px-4 text-left text-sm text-rose-400"
                >
                  Logout
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename="/mobile">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Home />} />
          <Route path="check" element={<CheckNumbers />} />
          <Route path="wheels" element={<Wheels />} />
          <Route path="backtest" element={<Backtest />} />
          <Route path="leaderboard" element={<Leaderboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
