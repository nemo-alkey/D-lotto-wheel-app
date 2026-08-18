import axios from 'axios';

const TOKEN_KEY = 'lotto_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      clearToken();
      // App is served under the /mobile/ basename (see vite.config.js).
      if (!window.location.pathname.endsWith('/login')) {
        window.location.href = `${import.meta.env.BASE_URL}login`;
      }
    }
    if (status === 429) {
      const retry = error.response?.data?.retry_after_seconds;
      const msg = retry
        ? `Rate limit exceeded. Please retry in ${retry} seconds.`
        : 'Rate limit exceeded. Please try again shortly.';
      return Promise.reject(new Error(msg));
    }
    const detail = error.response?.data?.detail;
    if (detail) {
      return Promise.reject(new Error(detail));
    }
    return Promise.reject(error);
  }
);

export async function login(username, password) {
  const { data } = await client.post('/token', { username, password });
  return data;
}

export async function register(username, password) {
  const { data } = await client.post('/register', { username, password });
  return data;
}

export async function getEnsemble(main = 20) {
  const { data } = await client.get('/predict/ensemble', { params: { main, bonus: 5, pb: 3 } });
  return data;
}

export async function listWheels() {
  const { data } = await client.get('/wheels');
  return data;
}

export async function getWheel(name) {
  const { data } = await client.get(`/wheel/${encodeURIComponent(name)}`);
  return data;
}

export async function checkNumbers(wheel, draw, powerball) {
  const { data } = await client.post('/check', { wheel, draw, powerball });
  return data;
}

export async function runBacktest(wheelName, draws) {
  const { data } = await client.get('/backtest/bonus_impact', {
    params: { wheel_name: wheelName, draws },
  });
  return data;
}

export async function getLeaderboard() {
  const { data } = await client.get('/leaderboard');
  return data;
}

export default client;
