import { useState, useEffect } from "react";
import { portalFetch } from "../api/client";

const FILMING_SETUPS = [
  { value: "solo", label: "Solo" },
  { value: "couple", label: "Casal" },
  { value: "small_group", label: "Grupo pequeno" },
  { value: "large_group", label: "Orgia / grupo grande" },
];

const LOCATION_TYPES = [
  { value: "home", label: "Casa" },
  { value: "hotel", label: "Hotel / Motel" },
  { value: "studio", label: "Estúdio" },
  { value: "outdoor", label: "Ar livre" },
];

const LEVEL_OPTIONS = [
  { value: "amateur", label: "Amador" },
  { value: "semi-pro", label: "Semi-profissional" },
  { value: "professional", label: "Profissional" },
];

function PillGroup({ label, hint, options, selected, onChange }) {
  function toggle(value) {
    onChange(
      selected.includes(value)
        ? selected.filter(v => v !== value)
        : [...selected, value]
    );
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">{label}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
      <div className="flex flex-wrap gap-2">
        {options.map(o => {
          const active = selected.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => toggle(o.value)}
              className={`rounded-full border px-4 py-1.5 text-sm transition-all ${
                active
                  ? "border-cyan-400 bg-cyan-400/15 text-cyan-300"
                  : "border-white/15 bg-white/5 text-slate-400 hover:border-white/30 hover:text-slate-200"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const [filmingSetups, setFilmingSetups] = useState([]);
  const [locationTypes, setLocationTypes] = useState([]);
  const [productionLevel, setProductionLevel] = useState("amateur");
  const [performerDescription, setPerformerDescription] = useState("");
  const [productionConstraints, setProductionConstraints] = useState("");
  const [preferredCategories, setPreferredCategories] = useState("");
  const [preferredTags, setPreferredTags] = useState("");

  useEffect(() => {
    portalFetch("/api/portal/me")
      .then(me => {
        setFilmingSetups(me.filming_setups || []);
        setLocationTypes(me.location_types || []);
        setProductionLevel(me.production_level || "amateur");
        setPerformerDescription(me.performer_description || "");
        setProductionConstraints(me.production_constraints || "");
        setPreferredCategories((me.preferred_categories || []).join(", "));
        setPreferredTags((me.preferred_tags || []).join(", "));
      })
      .catch(() => setError("Erro ao carregar perfil."))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await portalFetch("/api/portal/profile", {
        method: "PUT",
        body: JSON.stringify({
          filming_setups: filmingSetups,
          location_types: locationTypes,
          production_level: productionLevel,
          performer_description: performerDescription.trim() || null,
          production_constraints: productionConstraints.trim() || null,
          preferred_categories: preferredCategories.split(",").map(s => s.trim()).filter(Boolean),
          preferred_tags: preferredTags.split(",").map(s => s.trim()).filter(Boolean),
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e.message || "Erro ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex min-h-[200px] items-center justify-center text-slate-400 text-sm">Carregando…</div>;
  }

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <h1 className="text-xl font-semibold text-white">Meu Perfil de Produção</h1>
        <p className="mt-1 text-sm text-slate-400">
          O Trend Radar usa essas informações para sugerir cenas que você realmente consegue gravar.
        </p>
      </div>

      <div className="rounded-2xl border border-white/8 bg-slate-950/60 p-5 space-y-5">
        <PillGroup
          label="Tipos de cena"
          hint="Marque tudo que você consegue fazer"
          options={FILMING_SETUPS}
          selected={filmingSetups}
          onChange={setFilmingSetups}
        />
        <PillGroup
          label="Locais disponíveis"
          options={LOCATION_TYPES}
          selected={locationTypes}
          onChange={setLocationTypes}
        />
        <div className="space-y-1.5">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Equipamento</div>
          <div className="flex flex-wrap gap-2">
            {LEVEL_OPTIONS.map(o => (
              <button
                key={o.value}
                type="button"
                onClick={() => setProductionLevel(o.value)}
                className={`rounded-full border px-4 py-1.5 text-sm transition-all ${
                  productionLevel === o.value
                    ? "border-cyan-400 bg-cyan-400/15 text-cyan-300"
                    : "border-white/15 bg-white/5 text-slate-400 hover:border-white/30 hover:text-slate-200"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/8 bg-slate-950/60 p-5 space-y-4">
        <div className="space-y-1.5">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Descrição dos performers</div>
          <div className="text-xs text-slate-500">Físico de quem aparece — usado para gerar thumbnails realistas com IA</div>
          <input
            type="text"
            value={performerDescription}
            onChange={e => setPerformerDescription(e.target.value)}
            placeholder="Ex: morena 25 anos, corpo atlético, tatuagem no braço"
            className="w-full rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-400/40 focus:outline-none"
          />
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">O que você NÃO faz</div>
          <div className="text-xs text-slate-500">Sem isso o Trend Radar vai sugerir cena que você não consegue fazer</div>
          <input
            type="text"
            value={productionConstraints}
            onChange={e => setProductionConstraints(e.target.value)}
            placeholder="Ex: não faço anal, não apareço com rosto, máximo 2 pessoas"
            className="w-full rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-400/40 focus:outline-none"
          />
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Categorias</div>
          <input
            type="text"
            value={preferredCategories}
            onChange={e => setPreferredCategories(e.target.value)}
            placeholder="Amateur, Brazilian, MILF, Solo"
            className="w-full rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-400/40 focus:outline-none"
          />
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Tags habituais</div>
          <input
            type="text"
            value={preferredTags}
            onChange={e => setPreferredTags(e.target.value)}
            placeholder="brasileira, amadora, morena"
            className="w-full rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-400/40 focus:outline-none"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-300/20 bg-rose-400/8 px-4 py-3 text-sm text-rose-300">{error}</div>
      )}
      {saved && (
        <div className="rounded-xl border border-emerald-300/20 bg-emerald-400/8 px-4 py-3 text-sm text-emerald-300">Salvo!</div>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className="rounded-2xl bg-cyan-500 px-6 py-3 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-50 transition"
      >
        {saving ? "Salvando…" : "Salvar"}
      </button>
    </div>
  );
}
