const DEFAULT_BRANDING = {
  brand_name: "MetaPorn Agency",
  headline: "Creator Portal",
  tagline: "Seu painel de performance, uploads, tendências e ganhos em um só lugar.",
  primary_color: "#67e8f9",
  secondary_color: "#8b5cf6",
  accent_color: "#22d3ee",
  surface_color: "#0f172a",
  text_color: "#e2e8f0",
  logo_b64: "",
};

function sanitizeColor(value, fallback) {
  const raw = String(value || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(raw) || /^#[0-9a-fA-F]{3}$/.test(raw)) return raw;
  return fallback;
}

export function getPortalBranding(creator) {
  const src = creator?.portal_branding || {};
  return {
    brand_name: src.brand_name || DEFAULT_BRANDING.brand_name,
    headline: src.headline || DEFAULT_BRANDING.headline,
    tagline: src.tagline || DEFAULT_BRANDING.tagline,
    primary_color: sanitizeColor(src.primary_color, DEFAULT_BRANDING.primary_color),
    secondary_color: sanitizeColor(src.secondary_color, DEFAULT_BRANDING.secondary_color),
    accent_color: sanitizeColor(src.accent_color, DEFAULT_BRANDING.accent_color),
    surface_color: sanitizeColor(src.surface_color, DEFAULT_BRANDING.surface_color),
    text_color: sanitizeColor(src.text_color, DEFAULT_BRANDING.text_color),
    logo_b64: typeof src.logo_b64 === "string" ? src.logo_b64 : "",
  };
}

export function buildPortalThemeStyle(branding) {
  return {
    "--portal-primary": branding.primary_color,
    "--portal-secondary": branding.secondary_color,
    "--portal-accent": branding.accent_color,
    "--portal-surface": branding.surface_color,
    "--portal-text": branding.text_color,
    "--portal-bg-start": `${branding.surface_color}`,
    "--portal-bg-mid": `${branding.secondary_color}22`,
    "--portal-bg-end": `${branding.primary_color}18`,
  };
}
