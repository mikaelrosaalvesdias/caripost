import { useState } from "react";
import { portalLogin } from "../api/client";
import { buildPortalThemeStyle, getPortalBranding } from "../lib/branding";

export default function LoginPage({ onLogin, creator, entrySlug = "" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const branding = getPortalBranding(creator);
  const creatorName = creator?.name || branding.brand_name || "Criador";
  const entryUrl = entrySlug ? `criador.caripost.n8nmikael.com.br/${entrySlug}` : "criador.caripost.n8nmikael.com.br";

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const session = await portalLogin(email, password);
      onLogin(session);
    } catch (err) {
      setError(err.message || "Falha no login");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="portal-theme min-h-screen px-4 py-10"
      style={{
        ...buildPortalThemeStyle(branding),
        background: `linear-gradient(160deg, var(--portal-bg-start) 0%, var(--portal-bg-mid) 45%, var(--portal-bg-end) 100%)`,
        color: "var(--portal-text)",
      }}
    >
      <div className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-6xl items-center gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="portal-shell-card rounded-[36px] p-8">
          <div className="flex items-center gap-4">
            {branding.logo_b64 ? (
              <img
                src={branding.logo_b64}
                alt={branding.brand_name || "Logo"}
                className="h-16 w-16 rounded-2xl border border-black/10 bg-black/5 object-contain p-2"
              />
            ) : null}
            <div className="text-xs uppercase tracking-[0.35em]" style={{ color: "var(--portal-primary)" }}>
              {branding.brand_name || "Caripost Agency"}
            </div>
          </div>
          <div className="mt-5 inline-flex rounded-full border border-black/10 bg-black/5 px-4 py-2 text-[11px] uppercase tracking-[0.28em]" style={{ color: "var(--portal-primary)" }}>
            {entrySlug ? `Portal dedicado · ${creatorName}` : "Portal do criador"}
          </div>
          <h1 className="mt-4 max-w-xl font-display text-5xl font-semibold leading-tight">
            {branding.headline || "Seu cockpit de operação criativa, receita e agenda."}
          </h1>
          <p className="portal-theme-muted mt-5 max-w-2xl text-base leading-7">
            {branding.tagline || "Acompanhe vídeos publicados, tendências semanais, ganhos estimados e envie seus brutos para a esteira automatizada da agência."}
          </p>
          <div className="portal-soft-panel mt-6 rounded-[24px] px-4 py-3 text-sm">
            <div className="portal-theme-muted">Entrada deste portal</div>
            <div className="mt-1 font-medium" style={{ color: "var(--portal-text)" }}>{entryUrl}</div>
          </div>
          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <Feature title="Dashboards" text="Views, ganhos e publicações em um só lugar." />
            <Feature title="Upload" text="Envio direto para processamento e publicação automática." />
            <Feature title="Tendências" text="Briefings prontos com oportunidades da semana." />
          </div>
        </section>

        <section className="portal-shell-card rounded-[32px] p-8">
          <div className="font-display text-3xl font-semibold">Entrar no portal</div>
          <p className="portal-theme-muted mt-2 text-sm">
            Use o e-mail cadastrado pela agência e a senha do portal para acessar o ambiente personalizado.
          </p>

          <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-sm text-slate-500">E-mail</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="portal-input w-full rounded-2xl px-4 py-3 outline-none transition"
                placeholder="criador@email.com"
                required
              />
            </label>
            <label className="block">
              <span className="mb-2 block text-sm text-slate-500">Senha</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="portal-input w-full rounded-2xl px-4 py-3 outline-none transition"
                placeholder="••••••••"
                required
              />
            </label>

            {error ? <div className="rounded-2xl border border-rose-300/40 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

            <button
              type="submit"
              disabled={loading}
              className="portal-primary-btn w-full rounded-2xl px-4 py-3 font-medium transition disabled:cursor-wait disabled:opacity-70"
            >
              {loading ? "Entrando..." : "Acessar portal"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

function Feature({ title, text }) {
  return (
    <div className="portal-soft-panel rounded-[24px] p-4">
      <div className="font-medium" style={{ color: "var(--portal-text)" }}>{title}</div>
      <div className="portal-theme-muted mt-2 text-sm">{text}</div>
    </div>
  );
}
