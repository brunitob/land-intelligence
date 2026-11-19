import { FormEvent, useState } from "react";
import { api, ApiError } from "../api";
import { Spinner } from "./ui";

// Formulario estándar (usuario + contraseña con autocomplete) para que lo reconozcan los gestores de contraseñas.
export function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { username, password });
      setPassword("");
      onLogin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Probá de nuevo.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="card login-card stack" method="post" action="/api/auth/login" onSubmit={submit}>
        <div className="brand" style={{ justifyContent: "center", fontSize: 18 }}>
          <svg viewBox="0 0 32 32" aria-hidden>
            <path d="M2 26 L12 10 L18 18 L22 13 L30 26 Z" fill="var(--accent)" />
          </svg>
          Patagonia Land
        </div>
        <label className="field" htmlFor="username">
          Usuario
          <input
            id="username"
            name="username"
            className="input"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label className="field" htmlFor="password">
          Contraseña
          <input
            id="password"
            name="password"
            type="password"
            className="input"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <div className="alert error small" role="alert">
            {error}
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy || !username || !password}>
          {busy && <Spinner />} Ingresar
        </button>
      </form>
    </div>
  );
}
