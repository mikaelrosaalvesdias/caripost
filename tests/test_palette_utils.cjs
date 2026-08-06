const assert = require('node:assert/strict');
const test = require('node:test');

const palette = require('../app/os/palette-utils.js');

test('buildPayload persists exactly one canonical primary and keeps extra colors', () => {
  const rows = [
    { name: 'azul', hex: '#123456' },
    { name: 'dourado', hex: 'fa3' },
    { name: 'branco', hex: '#ffffff' },
  ];

  assert.deepEqual(palette.buildPayload(rows, 1), {
    primary: '#FFAA33',
    azul: '#123456',
    branco: '#FFFFFF',
  });
});

test('marking and removing colors keeps one deterministic primary', () => {
  const initial = palette.fromColors({ primary: '#111111', accent: '#222222', branco: '#FFFFFF' });
  const marked = palette.markPrimary(initial.rows, initial.primaryIndex, 1);
  assert.equal(marked.primaryIndex, 1);
  assert.equal(marked.rows[1].name, 'primary');
  assert.notEqual(marked.rows[0].name, 'primary');

  const removedExtra = palette.removeColor(marked.rows, marked.primaryIndex, 2);
  assert.equal(removedExtra.primaryIndex, 1);
  assert.deepEqual(palette.buildPayload(removedExtra.rows, removedExtra.primaryIndex), {
    primary: '#222222',
    cor1: '#111111',
  });

  const removedPrimary = palette.removeColor(removedExtra.rows, removedExtra.primaryIndex, 1);
  assert.equal(removedPrimary.primaryIndex, 0);
  assert.deepEqual(palette.buildPayload(removedPrimary.rows, removedPrimary.primaryIndex), {
    primary: '#111111',
  });
});

test('an empty palette gets a primary when the first manual color is added', () => {
  const result = palette.addColor([], -1, '#0af');
  assert.equal(result.primaryIndex, 0);
  assert.deepEqual(palette.buildPayload(result.rows, result.primaryIndex), { primary: '#00AAFF' });
});

test('pointToPixel maps CSS-scaled contain images and rejects letterbox clicks', () => {
  const rect = { left: 10, top: 20, width: 200, height: 200 };
  // Natural 4x2 image is rendered at 200x100, vertically centered from y=70 to y=170.
  assert.equal(palette.pointToPixel(110, 40, rect, 4, 2, 'contain'), null);
  assert.deepEqual(palette.pointToPixel(35, 95, rect, 4, 2, 'contain'), {
    x: 0,
    y: 0,
    xPct: 12.5,
    yPct: 25,
  });
  assert.deepEqual(palette.pointToPixel(209, 169, rect, 4, 2, 'contain'), {
    x: 3,
    y: 1,
    xPct: 99.5,
    yPct: 99,
  });
});

test('hex and sampled RGB values are normalized exactly', () => {
  assert.equal(palette.normalizeHex('bF5'), '#BBFF55');
  assert.equal(palette.normalizeHex('BFF500'), '#BFF500');
  assert.equal(palette.normalizeHex('#xyz'), '');
  assert.equal(palette.rgbToHex(191, 245, 0), '#BFF500');
});

test('role aliases are canonical and duplicate aliases are rejected', () => {
  assert.equal(palette.canonicalRole('Cor secundária'), 'secondary');
  assert.equal(palette.canonicalRole('Destaque'), 'accent');
  assert.throws(() => palette.buildPayload([
    { name: 'primary', hex: '#000000' },
    { name: 'accent', hex: '#111111' },
    { name: 'Destaque', hex: '#222222' },
  ], 0), /Nome de cor repetido: "accent"/);
});
