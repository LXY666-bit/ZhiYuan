import axios from 'axios';

const api = axios.create({
  timeout: 60000,
});

// Request interceptor: attach Bearer token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('accessToken');
      window.dispatchEvent(new CustomEvent('unauthorized'));
    }
    return Promise.reject(error);
  },
);

export default api;
