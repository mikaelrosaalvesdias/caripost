/* Caripost OS — helpers puros do editor de paleta (browser + testes Node). */
(function attachPaletteTools(root, factory) {
  const api = factory();
  if (root) root.mpPalette = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function paletteToolsFactory() {
  const PRIMARY_ALIASES = new Set([
    'primary', 'primarycolor', 'primarycolour', 'principal', 'primaria', 'corprincipal', 'corprimaria',
  ]);
  const ROLE_ALIASES = {
    secondary: 'secondary',
    secondarycolor: 'secondary',
    secondarycolour: 'secondary',
    secundaria: 'secondary',
    corsecundaria: 'secondary',
    accent: 'accent',
    accentcolor: 'accent',
    accentcolour: 'accent',
    destaque: 'accent',
    cordestaque: 'accent',
  };

  function compactName(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '');
  }

  function canonicalRole(value) {
    const compact = compactName(value);
    if (PRIMARY_ALIASES.has(compact)) return 'primary';
    return ROLE_ALIASES[compact] || '';
  }

  function normalizeHex(value) {
    let hex = String(value || '').trim().toUpperCase();
    if (!hex) return '';
    if (!hex.startsWith('#')) hex = '#' + hex;
    if (/^#[0-9A-F]{3}$/.test(hex)) {
      hex = '#' + hex.slice(1).split('').map(char => char + char).join('');
    }
    return /^#[0-9A-F]{6}$/.test(hex) ? hex : '';
  }

  function nextColorName(rows, prefix) {
    const base = String(prefix || 'cor').trim() || 'cor';
    const used = new Set((rows || []).map(row => String(row && row.name || '').trim().toLowerCase()));
    let number = 1;
    while (used.has((base + number).toLowerCase())) number += 1;
    return base + number;
  }

  function fromColors(colors) {
    const rows = Object.entries(colors && typeof colors === 'object' ? colors : {})
      .filter(([name, hex]) => String(name || '').trim() && String(hex || '').trim())
      .map(([name, hex]) => ({ name: String(name).trim(), hex: normalizeHex(hex) || String(hex).trim().toUpperCase() }));
    let primaryIndex = rows.findIndex(row => canonicalRole(row.name) === 'primary');
    if (primaryIndex < 0 && rows.length) primaryIndex = 0;
    return { rows, primaryIndex };
  }

  function addColor(rows, primaryIndex, hex) {
    const next = (rows || []).map(row => ({ ...row }));
    const isFirst = next.length === 0;
    next.push({
      name: isFirst ? 'primary' : nextColorName(next),
      hex: normalizeHex(hex) || '#888888',
    });
    return { rows: next, primaryIndex: isFirst ? 0 : primaryIndex };
  }

  function markPrimary(rows, currentIndex, nextIndex) {
    const next = (rows || []).map(row => ({ ...row }));
    if (nextIndex < 0 || nextIndex >= next.length) {
      return { rows: next, primaryIndex: -1 };
    }
    if (currentIndex >= 0 && currentIndex < next.length && currentIndex !== nextIndex
        && canonicalRole(next[currentIndex].name) === 'primary') {
      next[currentIndex].name = nextColorName(next.filter((_row, index) => index !== currentIndex));
    }
    next[nextIndex].name = 'primary';
    return { rows: next, primaryIndex: nextIndex };
  }

  function removeColor(rows, primaryIndex, removeIndex) {
    const next = (rows || []).filter((_row, index) => index !== removeIndex).map(row => ({ ...row }));
    if (!next.length) return { rows: [], primaryIndex: -1 };
    if (removeIndex === primaryIndex) {
      return markPrimary(next, -1, Math.min(removeIndex, next.length - 1));
    }
    const adjusted = removeIndex < primaryIndex ? primaryIndex - 1 : primaryIndex;
    return { rows: next, primaryIndex: adjusted };
  }

  function buildPayload(rows, primaryIndex) {
    if (!Array.isArray(rows) || !rows.length) {
      throw new Error('Adicione pelo menos uma cor principal.');
    }
    if (primaryIndex < 0 || primaryIndex >= rows.length) {
      throw new Error('Marque qual cor é a principal.');
    }
    const primaryHex = normalizeHex(rows[primaryIndex].hex);
    if (!primaryHex) throw new Error('A cor principal precisa ter um hexadecimal válido.');

    const payload = { primary: primaryHex };
    const used = new Set(['primary']);
    rows.forEach((row, index) => {
      if (index === primaryIndex) return;
      const rawName = String(row && row.name || '').trim();
      if (!rawName) throw new Error('Dê um nome para todas as cores adicionais.');
      const role = canonicalRole(rawName);
      if (role === 'primary') throw new Error('Só a cor marcada com a estrela pode se chamar primary.');
      const name = role || rawName;
      const key = name.toLowerCase();
      if (used.has(key)) throw new Error('Nome de cor repetido: "' + name + '".');
      const hex = normalizeHex(row.hex);
      if (!hex) throw new Error('Cor inválida em "' + name + '".');
      used.add(key);
      payload[name] = hex;
    });
    return payload;
  }

  function pointToPixel(clientX, clientY, rect, naturalWidth, naturalHeight, objectFit) {
    const width = Number(rect && rect.width) || 0;
    const height = Number(rect && rect.height) || 0;
    const naturalW = Number(naturalWidth) || 0;
    const naturalH = Number(naturalHeight) || 0;
    if (!width || !height || !naturalW || !naturalH) return null;

    let offsetX = 0;
    let offsetY = 0;
    let renderedW = width;
    let renderedH = height;
    if ((objectFit || 'contain') === 'contain') {
      const scale = Math.min(width / naturalW, height / naturalH);
      renderedW = naturalW * scale;
      renderedH = naturalH * scale;
      offsetX = (width - renderedW) / 2;
      offsetY = (height - renderedH) / 2;
    }
    const localX = Number(clientX) - Number(rect.left || 0) - offsetX;
    const localY = Number(clientY) - Number(rect.top || 0) - offsetY;
    if (localX < 0 || localY < 0 || localX >= renderedW || localY >= renderedH) return null;
    return {
      x: Math.min(naturalW - 1, Math.max(0, Math.floor(localX / renderedW * naturalW))),
      y: Math.min(naturalH - 1, Math.max(0, Math.floor(localY / renderedH * naturalH))),
      xPct: localX / renderedW * 100,
      yPct: localY / renderedH * 100,
    };
  }

  function rgbToHex(red, green, blue) {
    const channel = value => Math.max(0, Math.min(255, Math.round(Number(value) || 0)))
      .toString(16).padStart(2, '0').toUpperCase();
    return '#' + channel(red) + channel(green) + channel(blue);
  }

  return {
    normalizeHex,
    canonicalRole,
    fromColors,
    addColor,
    markPrimary,
    removeColor,
    buildPayload,
    pointToPixel,
    rgbToHex,
  };
});
