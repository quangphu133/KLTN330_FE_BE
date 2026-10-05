type TimedWordBoundary = {
  wordId: number;
  startTime: number;
  endTime: number;
};

export type WordSelection = {
  startWordId: number | null;
  endWordId: number | null;
};

export function hasWordSelection<T extends WordSelection>(
  selection: T,
): selection is T & { startWordId: number; endWordId: number } {
  return selection.startWordId !== null && selection.endWordId !== null;
}

// Keep the audio boundaries where the user placed them. Word roles are applied
// separately to words overlapping that interval, never to a nearby word in silence.
export function getAudioSelection(
  words: readonly TimedWordBoundary[],
  start: number,
  end: number,
) {
  const startTime = Math.min(start, end);
  const endTime = Math.max(start, end);
  const selected = endTime > startTime
    ? words.filter((word) => word.endTime > startTime && word.startTime < endTime)
    : [];

  return {
    startTime,
    endTime,
    startWordId: selected.length ? Math.min(...selected.map((word) => word.wordId)) : null,
    endWordId: selected.length ? Math.max(...selected.map((word) => word.wordId)) : null,
  };
}
