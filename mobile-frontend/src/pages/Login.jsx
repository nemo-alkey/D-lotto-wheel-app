import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login, register, setToken } from '../api/client.js';

export default function Login() {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const onSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'register') {
        await register(username, password);
      }
      const data = await login(username, password);
      setToken(data.access_token);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message || (mode === 'register' ? 'Registration failed' : 'Login failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4 text-neutral-100">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-center text-2xl font-bold">NZ Lotto</h1>
        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-6">
          <h2 className="text-lg font-semibold">{mode === 'login' ? 'Sign in' : 'Create account'}</h2>

          <div>
            <label className="mb-1 block text-sm text-neutral-400">Username</label>
            <input
              type="text"
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 text-sm"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm text-neutral-400">Password</label>
            <input
              type="password"
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 text-sm"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/50 p-3 text-sm text-rose-200">{error}</div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="min-h-[44px] w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            {submitting ? 'Please wait...' : mode === 'login' ? 'Sign in' : 'Register'}
          </button>

          <p className="text-center text-sm text-neutral-400">
            {mode === 'login' ? "Don't have an account? " : 'Already registered? '}
            <button
              type="button"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login');
                setError(null);
              }}
              className="text-emerald-400 underline"
            >
              {mode === 'login' ? 'Register' : 'Sign in'}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
