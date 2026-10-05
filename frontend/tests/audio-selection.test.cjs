const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/features/calls/call/audio-selection.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const selection = {};
new Function('exports', compiled)(selection);
const { getAudioSelection, hasWordSelection } = selection;

const words = Object.freeze([
  Object.freeze({ wordId: 0, startTime: 0, endTime: 0.3 }),
  Object.freeze({ wordId: 1, startTime: 0.3, endTime: 0.7 }),
  Object.freeze({ wordId: 2, startTime: 1.2, endTime: 1.6 }),
  Object.freeze({ wordId: 3, startTime: 1.6, endTime: 2 }),
]);

test('a region keeps the exact mouse boundaries instead of snapping to words', () => {
  assert.deepEqual(getAudioSelection(words, 1.31, 1.89), {
    startTime: 1.31, endTime: 1.89, startWordId: 2, endWordId: 3,
  });
});

test('dragging right to left selects the same audio interval', () => {
  assert.deepEqual(getAudioSelection(words, 1.89, 1.31), getAudioSelection(words, 1.31, 1.89));
});

test('touching a word boundary does not also select the adjacent word', () => {
  assert.deepEqual(getAudioSelection(words, 0.3, 0.7), {
    startTime: 0.3, endTime: 0.7, startWordId: 1, endWordId: 1,
  });
});

test('selecting silence preserves the interval without assigning a nearby word', () => {
  const result = getAudioSelection(words, 0.8, 1.1);
  assert.deepEqual(result, {
    startTime: 0.8, endTime: 1.1, startWordId: null, endWordId: null,
  });
  assert.equal(hasWordSelection(result), false);
});

test('a zero-length interval does not assign a word', () => {
  assert.equal(hasWordSelection(getAudioSelection(words, 0.5, 0.5)), false);
});

test('moving a region changes its assigned words without changing its duration', () => {
  const original = getAudioSelection(words, 0.1, 0.5);
  const moved = getAudioSelection(words, 1.3, 1.7);
  assert.equal(original.startWordId, 0);
  assert.equal(moved.startWordId, 2);
  assert.ok(Math.abs((original.endTime - original.startTime) - (moved.endTime - moved.startTime)) < 1e-9);
});

test('word IDs remain valid when timestamps overlap and words are not sorted', () => {
  const result = getAudioSelection([
    { wordId: 9, startTime: 1, endTime: 2 },
    { wordId: 7, startTime: 1, endTime: 1.8 },
  ], 1.1, 1.7);
  assert.equal(result.startWordId, 7);
  assert.equal(result.endWordId, 9);
  assert.equal(hasWordSelection(result), true);
});
