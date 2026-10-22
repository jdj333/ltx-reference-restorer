import { useEffect, useState } from 'react';

type DecodedFrame = { image: HTMLImageElement; url: string };
type Pair = { key: string; source: DecodedFrame; output: DecodedFrame };

/** Publish the pair only after both images decode. A late response never relabels
 * an older frame, and scrubbing does not launch an extraction on every event. */
export function useExactFrames(jobId: string | undefined, frame: number, paused: boolean) {
  const [pair, setPair] = useState<Pair>();
  const [failure, setFailure] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const key = `${jobId || ''}:${frame}:${attempt}`;
  useEffect(() => {
    if (!jobId || !paused) return;
    let active = true;
    const abort = new AbortController();
    const urls: string[] = [];
    setPair(undefined); setFailure(undefined);
    async function load(view: 'source' | 'output'): Promise<DecodedFrame> {
      const response = await fetch(`/api/jobs/${jobId}/frame?frame=${frame}&view=${view}`, { signal: abort.signal, cache: 'no-store' });
      if (!response.ok) throw new Error('Exact frame unavailable');
      const blob = await response.blob();
      if (!active) throw new Error('Frame request superseded');
      const url = URL.createObjectURL(blob); urls.push(url);
      const image = new Image(); image.src = url;
      await image.decode();
      if (!active) throw new Error('Frame request superseded');
      return { image, url };
    }
    const timer = setTimeout(() => {
      Promise.all([load('source'), load('output')]).then(([source, output]) => {
        if (active) setPair({ key, source, output });
      }).catch(() => { if (active) { abort.abort(); setFailure(key); } });
    }, 140);
    return () => { active = false; clearTimeout(timer); abort.abort(); urls.forEach(url => URL.revokeObjectURL(url)); };
  }, [jobId, frame, paused, key]);
  const ready = paused && pair?.key === key;
  return { clear: () => setPair(undefined), pair: ready ? pair : undefined, failed: paused && failure === key, retry: () => { setPair(undefined); setFailure(undefined); setAttempt(value => value + 1); } };
}
