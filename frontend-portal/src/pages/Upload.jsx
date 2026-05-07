import { useCallback, useEffect, useRef, useState } from "react";
import SectionCard from "../components/SectionCard";
import { portalFetch, getToken, buildApiUrl } from "../api/client";

// ─── helpers ─────────────────────────────────────────────────────────────────
function fmtBytes(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(1) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b >= 1e3) return (b / 1e3).toFixed(0) + " KB";
  return b + " B";
}

// ─── Job status poller ────────────────────────────────────────────────────────
function useJobPoller(jobId) {
  const [job, setJob] = useState(null);
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    async function poll() {
      while (active) {
        try {
          const data = await portalFetch(`/api/portal/upload-job/${jobId}`);
          setJob(data);
          if (["done", "error", "failed"].includes(data.status)) break;
        } catch { break; }
        await new Promise(r => setTimeout(r, 3000));
      }
    }
    poll();
    return () => { active = false; };
  }, [jobId]);
  return job;
}

// ─── Single file upload with XHR progress ────────────────────────────────────
function uploadFile({ file, titleHint, onProgress, onDone, onError }) {
  const form = new FormData();
  form.append("file", file);
  form.append("title_hint", titleHint || file.name);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", buildApiUrl("/api/portal/upload-raw"));
  xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);

  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
  };
  xhr.onload = () => {
    try {
      const res = JSON.parse(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) onDone(res);
      else onError(res.detail || `Erro ${xhr.status}`);
    } catch { onError("Resposta inválida do servidor"); }
  };
  xhr.onerror = () => onError("Falha de conexão");
  xhr.send(form);
  return xhr;
}

// ─── FileRow ──────────────────────────────────────────────────────────────────
function FileRow({ item, onRemove }) {
  const job = useJobPoller(item.jobId);
  const status = job?.status || item.status;
  const progress = item.status === "uploading" ? item.uploadPct
    : job ? job.progress_pct : 0;

  const statusColor = {
    pending: "text-slate-400",
    uploading: "text-cyan-300",
    queued: "text-amber-300",
    processing: "text-violet-300",
    done: "text-emerald-300",
    error: "text-rose-300",
    failed: "text-rose-300",
  }[status] || "text-slate-400";

  const statusLabel = {
    pending: "Aguardando",
    uploading: `Enviando ${item.uploadPct}%`,
    queued: "Na fila de processamento",
    processing: job?.detail ? `${job.detail} (${job?.progress_pct ?? 0}%)` : `Processando ${job?.progress_pct ?? 0}%`,
    done: "Concluído ✓",
    error: job?.detail || "Erro",
    failed: job?.detail || "Falhou",
  }[status] || status;

  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 px-4 py-3 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-white truncate">{item.file.name}</div>
          <div className="text-xs text-slate-500 mt-0.5">{fmtBytes(item.file.size)}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-xs ${statusColor}`}>{statusLabel}</span>
          {status === "pending" && (
            <button onClick={() => onRemove(item.id)} className="text-slate-600 hover:text-slate-400 text-xs">✕</button>
          )}
        </div>
      </div>
      {(status === "uploading" || status === "processing") && (
        <div className="h-1.5 rounded-full bg-white/8 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${status === "uploading" ? "bg-cyan-400" : "bg-violet-400"}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

// ─── UploadTab ────────────────────────────────────────────────────────────────
function UploadTab({ titleHint, setTitleHint, isParts, setIsParts }) {
  const [files, setFiles] = useState([]);
  const [running, setRunning] = useState(false);
  const inputRef = useRef(null);

  function addFiles(newFiles) {
    const items = Array.from(newFiles).map(f => ({
      id: crypto.randomUUID(),
      file: f,
      status: "pending",
      uploadPct: 0,
      jobId: null,
    }));
    setFiles(prev => [...prev, ...items]);
  }

  function removeFile(id) {
    setFiles(prev => prev.filter(f => f.id !== id));
  }

  function onDrop(e) {
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  }

  async function handleSend() {
    const pending = files.filter(f => f.status === "pending");
    if (!pending.length) return;
    setRunning(true);

    for (let i = 0; i < pending.length; i++) {
      const item = pending[i];
      const hint = isParts
        ? `${titleHint || "serie"} - parte ${i + 1}`
        : (titleHint || item.file.name);

      setFiles(prev => prev.map(f => f.id === item.id ? { ...f, status: "uploading", uploadPct: 0 } : f));

      await new Promise((resolve) => {
        uploadFile({
          file: item.file,
          titleHint: hint,
          onProgress: (pct) => {
            setFiles(prev => prev.map(f => f.id === item.id ? { ...f, uploadPct: pct } : f));
          },
          onDone: (res) => {
            setFiles(prev => prev.map(f => f.id === item.id
              ? { ...f, status: "queued", jobId: res.job_id }
              : f));
            resolve();
          },
          onError: (err) => {
            setFiles(prev => prev.map(f => f.id === item.id
              ? { ...f, status: "error", detail: err }
              : f));
            resolve();
          },
        });
      });
    }
    setRunning(false);
  }

  const pendingCount = files.filter(f => f.status === "pending").length;

  return (
    <div className="space-y-5">
      <div
        onDrop={onDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        className="rounded-2xl border-2 border-dashed border-white/15 bg-white/3 hover:bg-white/5 hover:border-white/25 transition cursor-pointer px-6 py-10 text-center"
      >
        <div className="text-3xl mb-2">📁</div>
        <div className="text-sm text-slate-300">Clique ou arraste os arquivos aqui</div>
        <div className="text-xs text-slate-500 mt-1">MP4, MOV, MKV — múltiplos arquivos permitidos</div>
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          multiple
          className="hidden"
          onChange={e => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <div className="space-y-2">
          {files.map(item => (
            <FileRow key={item.id} item={item} onRemove={removeFile} />
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-xs text-slate-400 uppercase tracking-widest">Título / Observação</span>
          <input
            type="text"
            value={titleHint}
            onChange={e => setTitleHint(e.target.value)}
            placeholder="Ex.: cena praiana versão longa"
            className="w-full rounded-2xl border border-white/10 bg-white/6 px-4 py-2.5 text-sm text-white outline-none focus:border-cyan-300/40"
          />
        </label>
      </div>

      {files.length > 1 && (
        <label className="flex items-center gap-3 cursor-pointer select-none rounded-2xl border border-amber-300/15 bg-amber-400/6 px-4 py-3">
          <input
            type="checkbox"
            checked={isParts}
            onChange={e => setIsParts(e.target.checked)}
            className="w-4 h-4 accent-amber-400"
          />
          <div>
            <div className="text-sm text-amber-200">São partes do mesmo vídeo</div>
            <div className="text-xs text-amber-200/60 mt-0.5">
              Cada parte será processada com o mesmo título base (parte 1, 2, 3…)
            </div>
          </div>
        </label>
      )}

      <button
        onClick={handleSend}
        disabled={running || pendingCount === 0}
        className="w-full rounded-2xl bg-cyan-400 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-300 disabled:opacity-40 transition"
      >
        {running
          ? "Enviando…"
          : `Enviar ${pendingCount > 0 ? pendingCount + " " : ""}arquivo${pendingCount !== 1 ? "s" : ""}`}
      </button>
    </div>
  );
}

// ─── DriveJobRow ──────────────────────────────────────────────────────────────
function DriveJobRow({ jobId, name }) {
  const job = useJobPoller(jobId);
  const status = job?.status || "aguardando";
  const pct = job?.progress_pct ?? 0;
  const done = ["done", "error", "failed"].includes(status);
  return (
    <div className="rounded-2xl border border-white/8 bg-white/3 px-4 py-3 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-sm text-white truncate">{name}</div>
        <div className="text-xs text-slate-400 mt-0.5">
          {status === "done" ? "Concluído ✓" : job?.detail || status}
        </div>
      </div>
      {!done && (
        <div className="w-20 h-1.5 rounded-full bg-white/8 overflow-hidden">
          <div className="h-full rounded-full bg-violet-400 transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
      {status === "done" && <span className="text-emerald-400 text-lg">✓</span>}
      {(status === "error" || status === "failed") && <span className="text-rose-400 text-lg">✗</span>}
    </div>
  );
}

// ─── DriveTab ─────────────────────────────────────────────────────────────────
function DriveTab({ titleHint, setTitleHint }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await portalFetch("/api/portal/drive-files");
      setFiles(data.files || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function toggleSelect(id) {
    setSelected(prev => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });
  }

  async function importSelected() {
    const toImport = files.filter(f => selected.has(f.id));
    for (const f of toImport) {
      try {
        const res = await portalFetch("/api/portal/drive-import", {
          method: "POST",
          body: JSON.stringify({
            drive_file_id: f.id,
            filename: f.name,
            title_hint: titleHint || f.name,
          }),
        });
        setJobs(prev => [...prev, { jobId: res.job_id, name: f.name }]);
        setSelected(prev => { const s = new Set(prev); s.delete(f.id); return s; });
      } catch (e) {
        setError(`Erro ao importar ${f.name}: ${e.message}`);
      }
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-slate-400">Arquivos na sua pasta do Google Drive</div>
        <button onClick={load} disabled={loading} className="text-xs text-cyan-400 hover:text-cyan-300 disabled:opacity-40">
          {loading ? "Carregando…" : "↻ Atualizar"}
        </button>
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {!loading && files.length === 0 && !error && (
        <div className="rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center text-sm text-slate-500">
          Nenhum arquivo encontrado na pasta do Drive.<br />
          <span className="text-xs mt-1 block">Faça upload dos vídeos na pasta compartilhada com a agência.</span>
        </div>
      )}

      {loading && (
        <div className="space-y-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="rounded-2xl border border-white/8 bg-white/3 h-16 animate-pulse" />
          ))}
        </div>
      )}

      <div className="space-y-2">
        {files.map(f => (
          <label
            key={f.id}
            className={`flex items-center gap-3 rounded-2xl border px-4 py-3 cursor-pointer transition ${
              selected.has(f.id)
                ? "border-cyan-300/30 bg-cyan-300/6"
                : "border-white/8 bg-white/3 hover:bg-white/5"
            }`}
          >
            <input
              type="checkbox"
              checked={selected.has(f.id)}
              onChange={() => toggleSelect(f.id)}
              className="w-4 h-4 accent-cyan-400"
            />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-white truncate">{f.name}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {f.size ? fmtBytes(Number(f.size)) : ""}
                {f.modifiedTime ? ` · ${f.modifiedTime.slice(0, 10)}` : ""}
              </div>
            </div>
          </label>
        ))}
      </div>

      {jobs.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-1">Importações em andamento</div>
          {jobs.map(j => <DriveJobRow key={j.jobId} jobId={j.jobId} name={j.name} />)}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-xs text-slate-400 uppercase tracking-widest">Título / Observação</span>
          <input
            type="text"
            value={titleHint}
            onChange={e => setTitleHint(e.target.value)}
            placeholder="Ex.: vídeo praia julho"
            className="w-full rounded-2xl border border-white/10 bg-white/6 px-4 py-2.5 text-sm text-white outline-none focus:border-cyan-300/40"
          />
        </label>
      </div>

      <button
        onClick={importSelected}
        disabled={selected.size === 0}
        className="w-full rounded-2xl bg-cyan-400 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-300 disabled:opacity-40 transition"
      >
        Importar {selected.size > 0 ? selected.size + " " : ""}arquivo{selected.size !== 1 ? "s" : ""}
      </button>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function UploadPage() {
  const [tab, setTab] = useState("upload");
  const [driveConfigured, setDriveConfigured] = useState(false);
  const [titleHint, setTitleHint] = useState("");
  const [isParts, setIsParts] = useState(false);

  useEffect(() => {
    portalFetch("/api/portal/drive-status")
      .then(d => setDriveConfigured(d.configured))
      .catch(() => setDriveConfigured(false));
  }, []);

  return (
    <SectionCard
      title="Enviar vídeo"
      subtitle="Upload direto ou via Google Drive."
    >
      {/* Tabs */}
      <div className="flex gap-1 rounded-2xl border border-white/8 bg-white/3 p-1 mb-6">
        <button
          onClick={() => setTab("upload")}
          className={`flex-1 rounded-xl py-2 text-sm font-medium transition ${
            tab === "upload" ? "bg-cyan-400/15 text-cyan-200" : "text-slate-400 hover:text-slate-200"
          }`}
        >
          📤 Upload direto
        </button>
        <button
          onClick={() => driveConfigured && setTab("drive")}
          className={`flex-1 rounded-xl py-2 text-sm font-medium transition ${
            tab === "drive"
              ? "bg-cyan-400/15 text-cyan-200"
              : driveConfigured
              ? "text-slate-400 hover:text-slate-200"
              : "text-slate-600 cursor-not-allowed"
          }`}
          title={driveConfigured ? "" : "Google Drive não configurado para esta conta"}
        >
          {driveConfigured ? "📂 Google Drive" : "📂 Drive (não ativo)"}
        </button>
      </div>

      {tab === "upload" && (
        <UploadTab
          titleHint={titleHint} setTitleHint={setTitleHint}
          isParts={isParts} setIsParts={setIsParts}
        />
      )}
      {tab === "drive" && driveConfigured && (
        <DriveTab
          titleHint={titleHint} setTitleHint={setTitleHint}
        />
      )}
    </SectionCard>
  );
}
