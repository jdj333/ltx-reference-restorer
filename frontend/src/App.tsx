import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, PointerEvent, ReactNode, RefObject } from 'react';
import { api } from './api';
import { Modal } from './Modal';
import { LocalFilePicker } from './LocalFilePicker';
import { CropEditor } from './CropEditor';
import { SystemStatus } from './SystemStatus';
import { useExactFrames } from './useExactFrames';
import type { DemoResult } from './SystemStatus';
import type { Actor, Backend, Guide, Job, Placement, Preset, Project, ProjectDetail, Reference, Setup, Shot, Source } from './types';

type View = 'sources' | 'actors' | 'setup' | 'queue' | 'compare' | 'system';
type IconName = 'film' | 'folder' | 'people' | 'frame' | 'queue' | 'compare' | 'plus' | 'arrow' | 'check' | 'close' | 'play' | 'pause' | 'refresh' | 'info';
const paths: Record<IconName, string> = {
  film: 'M4 3h16v18H4z M4 8h16M4 16h16M8 3v18M16 3v18', folder: 'M3 6h6l2 3h10v11H3z',
  people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.9M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  frame: 'M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5M7 7h10v10H7z',
  queue: 'M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1', compare: 'M3 4h18v16H3zM12 4v16M7 9l-2 3 2 3M17 9l2 3-2 3',
  plus: 'M12 5v14M5 12h14', arrow: 'M5 12h14M13 6l6 6-6 6', check: 'M5 12l4 4L19 6', close: 'M6 6l12 12M6 18L18 6',
  play: 'M8 5l12 7-12 7z', pause: 'M8 5v14M16 5v14', refresh: 'M20 8a8 8 0 1 0 1 7M20 3v5h-5', info: 'M12 11v6M12 7v.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
};
function Icon({ name, size = 18 }: { name: IconName; size?: number }) { return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>; }
function fmt(value: number | undefined) { if (value === undefined || !Number.isFinite(value)) return '—'; const minutes = Math.floor(value / 60); return `${String(minutes).padStart(2, '0')}:${(value % 60).toFixed(2).padStart(5, '0')}`; }
function human(value: string | undefined) { return value ? value.replaceAll('_', ' ') : '—'; }
function shortHash(value?: string) { return value ? `${value.slice(0, 12)}…` : 'Not available'; }
function date(value?: string) { return value ? new Date(value).toLocaleString() : '—'; }
function Status({ state }: { state?: string }) { return <span className={`status ${state || 'pending'}`}><span />{human(state || 'pending')}</span>; }
function Empty({ icon = 'film', title, children }: { icon?: IconName; title: string; children?: ReactNode }) { return <div className="empty"><span className="empty-icon"><Icon name={icon} size={28} /></span><h3>{title}</h3><div>{children}</div></div>; }
function Field({ label, children, hint, className = '' }: { label: string; children: ReactNode; hint?: string; className?: string }) { return <label className={`field ${className}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
function Panel({ title, subtitle, action, children, className = '' }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{title && <header className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>}{children}</section>; }
const tabs: { id: View; label: string; icon: IconName; number: string }[] = [
  { id: 'sources', label: 'Sources & shots', icon: 'film', number: '01' }, { id: 'actors', label: 'Actor library', icon: 'people', number: '02' },
  { id: 'setup', label: 'Shot setup', icon: 'frame', number: '03' }, { id: 'queue', label: 'Render queue', icon: 'queue', number: '04' },
  { id: 'compare', label: 'Compare & review', icon: 'compare', number: '05' },
  { id: 'system', label: 'Setup & status', icon: 'info', number: '06' },
];
const emptySetup: Setup = { reference_ids: [], keyframes: [], interpolation: 'linear' };

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(localStorage.getItem('restorer-project') || '');
  const [storedDetail, setDetail] = useState<ProjectDetail | null>(null);
  // Never render or act on the previous workspace while the next one loads.
  const detail = storedDetail?.project.id === projectId ? storedDetail : null;
  const activeProject = useRef(projectId);
  activeProject.current = projectId;
  const [backends, setBackends] = useState<Backend[]>([]);
  const [view, setView] = useState<View>('sources');
  const [shotId, setShotId] = useState('');
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const setupDirty = useRef(false);
  const trackDirty = useCallback((dirty: boolean) => { setupDirty.current = dirty; }, []);
  function canLeaveSetup() {
    if (!setupDirty.current) return true;
    if (!window.confirm('Discard unsaved shot setup changes? Save the setup first to keep actor references and placement.')) return false;
    return true;
  }
  function navigate(next: View) { if (next !== view && canLeaveSetup()) setView(next); }
  useEffect(() => { const guard = (event: BeforeUnloadEvent) => { if (setupDirty.current) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard); }, []);
  const refresh = useCallback(async () => {
    const [list, engines] = await Promise.all([api<Project[]>('/projects'), api<Backend[]>('/backends')]);
    setProjects(list); setBackends(engines);
    if (activeProject.current !== projectId) return;
    if (projectId && list.some(p => p.id === projectId)) {
      const data = await api<ProjectDetail>(`/projects/${projectId}`);
      if (activeProject.current === projectId) setDetail({ ...data, notes: data.notes || [] });
    } else if (list.length) setProjectId(list[0].id);
    else { setDetail(null); if (projectId) setProjectId(''); }
  }, [projectId]);
  useEffect(() => { let alive = true; setLoading(true); refresh().catch(e => alive && setError(e.message)).finally(() => alive && setLoading(false)); return () => { alive = false; }; }, [refresh]);
  useEffect(() => { if (projectId) localStorage.setItem('restorer-project', projectId); }, [projectId]);
  useEffect(() => {
    if (!detail?.jobs.some(j => ['queued', 'running'].includes(j.state))) return;
    const timer = setInterval(() => { api<ProjectDetail>(`/projects/${projectId}`).then(data => { if (activeProject.current === projectId) setDetail({ ...data, notes: data.notes || [] }); }).catch(() => {}); }, 2000);
    return () => clearInterval(timer);
  }, [detail?.jobs, projectId]);
  async function act(fn: () => Promise<unknown>, success?: string) {
    setBusy(true); setError(''); setNotice('');
    try { await fn(); await refresh(); if (success) setNotice(success); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  const selectedShot = detail?.shots.find(s => s.id === shotId) || detail?.shots[0];
  const selectedJob = detail?.jobs.find(j => j.id === jobId) || detail?.jobs.at(-1);
  const openShot = (id: string) => { if (canLeaveSetup()) { setShotId(id); setView('setup'); } };
  const changeShot = (id: string) => { if (canLeaveSetup()) setShotId(id); };
  async function tryDemo() {
    if (!canLeaveSetup()) return;
    await act(async () => { const demo = await api<DemoResult>('/demo', {}); setProjectId(demo.project_id); setJobId(demo.job_id); setView('queue'); }, 'Synthetic demo opened. The labeled baseline job is processed by the background worker.');
  }
  const openJob = (id: string) => { setJobId(id); setView('compare'); };
  const currentTab = tabs.find(t => t.id === view)!;
  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!canLeaveSetup()) return;
    await act(async () => { const project = await api<Project>('/projects', { name: projectName }); setProjectId(project.id); setCreateOpen(false); setProjectName(''); }, 'Project created. Import a source to begin.');
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Reference Restorer home" onClick={event => { event.preventDefault(); navigate('sources'); }}><span className="brand-mark"><Icon name="frame" size={23} /></span><span>REFERENCE<span>RESTORER</span></span></a>
      <div className="workspace-label">LOCAL WORKSPACE</div>
      <div className="project-picker"><Icon name="folder" /><select aria-label="Open project" value={projectId} onChange={e => { if (canLeaveSetup()) { setProjectId(e.target.value); setShotId(''); setJobId(''); } }}><option value="" disabled>Select a project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><button className="icon-button" aria-label="Create project" title="Create project" onClick={event => { event.currentTarget.focus(); setCreateOpen(true); }}><Icon name="plus" size={16} /></button></div>
      <nav>{tabs.map(tab => <button key={tab.id} className={`nav-item ${view === tab.id ? 'active' : ''}`} aria-current={view === tab.id ? 'page' : undefined} onClick={() => navigate(tab.id)}><Icon name={tab.icon} /><span>{tab.label}</span><small>{tab.number}</small></button>)}</nav>
      <div className="sidebar-principle"><span className="eyebrow">THE RESTORATION PRINCIPLE</span><p>The source film supplies the performance.</p><p>Approved references guide appearance and detail.</p><span className="fineprint">Every render is a candidate for human review.</span></div>
      <div className="local-status"><span className="dot" />Local application<span>v0.1</span></div>
    </aside>
    <main>
      <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> {detail?.project.name || 'New restoration'}</div><div className="topbar-right"><span className="local-pill"><span className="dot" /> Local files</span><button className="icon-button" aria-label="Refresh project" onClick={() => act(refresh)} disabled={busy}><Icon name="refresh" size={16} /></button></div></header>
      <div className="main-content">
        <div className="page-heading"><div><span className="eyebrow">RESTORATION WORKSPACE <span className="heading-index">/ {currentTab.number}</span></span><h1>{currentTab.label}</h1><p>{({ sources: 'Original recordings, carefully prepared. Define the performance you want to restore.', actors: 'Keep your evidence organized. Only approved references can guide a render.', setup: 'Place the reference, inspect the guide, then create a new render version.', queue: 'One render at a time. Every output keeps its settings and provenance.', compare: 'Look closely. Technical integrity and performance fidelity require separate review.', system: 'Check local tools, worker activity, storage, and the exact requirements for LTX rendering.' })[view]}</p></div>{detail && <span className="project-badge"><Icon name="folder" size={15} />{detail.project.name}</span>}</div>
        {error && <div className="alert error" role="alert"><Icon name="info" /><div><strong>Action could not be completed</strong><p>{error}</p></div><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={16} /></button></div>}
        {notice && <div className="alert success" role="status"><Icon name="check" /><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notification"><Icon name="close" size={16} /></button></div>}
        {view === 'system' ? <SystemStatus onDemo={tryDemo} busy={busy} /> : (loading || !!projectId) && !detail ? <Panel><div className="loading">{loading || !error ? <><span className="spinner" />Opening workspace…</> : 'Could not open this project. Refresh to retry.'}</div></Panel> : !detail ? <div className="welcome-grid"><Panel className="welcome-panel"><span className="large-frame"><Icon name="film" size={46} /></span><span className="eyebrow">A NEW CHAPTER FOR OLD FILM</span><h2>Restore the detail.<br />Preserve the performance.</h2><p>Create a project to organize source recordings, build an approved actor library, and compare every result with the original.</p><button className="primary" onClick={event => { event.currentTarget.focus(); setCreateOpen(true); }}><Icon name="plus" />Create your first project</button><button className="secondary" disabled={busy} onClick={tryDemo}>Try synthetic demo</button><button className="text-button" onClick={() => navigate('system')}>Check setup & status</button></Panel><Panel title="A complete local workflow"><ol className="onboarding-steps"><li><b>01</b><div><strong>Start with the source</strong><p>Import a local video and select a short shot. Originals stay untouched.</p></div></li><li><b>02</b><div><strong>Prepare your references</strong><p>Record provenance, approve actor images, and place a face region.</p></div></li><li><b>03</b><div><strong>Render and review</strong><p>Start with a conventional baseline. LTX requires a configured, verified backend.</p></div></li></ol></Panel></div> : <>
          <div className="project-strip"><span><b>{String(detail.sources.length).padStart(2, '0')}</b> source recordings</span><span><b>{String(detail.shots.length).padStart(2, '0')}</b> shots</span><span><b>{String(detail.actors.length).padStart(2, '0')}</b> actors</span><span><b>{String(detail.jobs.filter(j => j.state === 'succeeded').length).padStart(2, '0')}</b> rendered versions</span><span className="strip-end"><span className="dot" /> Originals preserved</span></div>
          {view === 'sources' && <Sources key={detail.project.id} detail={detail} busy={busy} act={act} openShot={openShot} />}
          {view === 'actors' && <Actors key={detail.project.id} detail={detail} busy={busy} act={act} />}
          {view === 'setup' && <ShotSetup key={detail.project.id} detail={detail} shot={selectedShot} setShotId={changeShot} onDirtyChange={trackDirty} backends={backends} busy={busy} act={act} onQueued={() => setView('queue')} />}
          {view === 'queue' && <Queue key={detail.project.id} detail={detail} selectedJob={selectedJob} setJobId={setJobId} busy={busy} act={act} openJob={openJob} backends={backends} />}
          {view === 'compare' && <Comparison key={detail.project.id} detail={detail} job={selectedJob} setJobId={setJobId} busy={busy} act={act} />}
        </>}
        <footer className="page-footer"><span>Source performance first. Human approval always.</span><span>No model weights are downloaded automatically.</span></footer>
      </div>
    </main>
    {createOpen && <Modal titleId="project-title" onClose={() => setCreateOpen(false)} busy={busy}><div className="modal-head"><span className="eyebrow">START A RESTORATION</span><button className="icon-button" aria-label="Close dialog" disabled={busy} onClick={() => setCreateOpen(false)}><Icon name="close" /></button></div><h2 id="project-title">Create a project</h2><p>Sources, actor references, render versions, and reviews stay together.</p><form onSubmit={createProject}><Field label="Project name"><input data-autofocus autoFocus required maxLength={160} placeholder="e.g. Family film · reel 03" value={projectName} onChange={e => setProjectName(e.target.value)} /></Field><button className="primary full-width" disabled={busy || !projectName.trim()}>{busy ? 'Creating…' : 'Create project'}<Icon name="arrow" /></button></form></Modal>}
  </div>;
}

type Action = (fn: () => Promise<unknown>, success?: string) => Promise<void>;

function Sources({ detail, busy, act, openShot }: { detail: ProjectDetail; busy: boolean; act: Action; openShot: (id: string) => void }) {
  const [path, setPath] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [sourceId, setSourceId] = useState(detail.sources[0]?.id || '');
  const source = detail.sources.find(s => s.id === sourceId) || detail.sources[0];
  const [name, setName] = useState('');
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(2);
  const [previewFailed, setPreviewFailed] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => { setStart(0); setEnd(Math.min(2, source?.duration || 2)); setPreviewFailed(false); }, [source?.id]);
  async function importSource(e: FormEvent) { e.preventDefault(); await act(async () => { const item = await api<Source>(`/projects/${detail.project.id}/sources`, { path }); setSourceId(item.id); setPath(''); }, 'Source imported. Original file preserved.'); }
  async function createShot(e: FormEvent) { e.preventDefault(); if (!source) return; await act(async () => { const shot = await api<Shot>(`/projects/${detail.project.id}/shots`, { source_id: source.id, name: name || `Shot ${detail.shots.length + 1}`, start_time: start, end_time: end }); setName(''); openShot(shot.id); }, 'Shot created. Add an actor and place a face region when needed.'); }
  return <div className="sources-layout">
    <Panel title="Source recordings" subtitle="Choose a video from a configured local import folder. No upload to an external service." className="span-full"><form className="local-import-form" onSubmit={importSource}><div className="import-actions"><button type="button" className="secondary" onClick={event => { event.currentTarget.focus(); setBrowsing(true); }}>Browse local videos</button><span className="selected-file">{path ? path.split(/[\\/]/).at(-1) : "No video selected"}</span><button className="primary" disabled={busy || !path.trim()}><Icon name="plus" />Import video</button></div><label className="checkbox-field"><input type="checkbox" checked={advanced} onChange={e => setAdvanced(e.target.checked)} />Enter an advanced local path</label>{advanced && <Field label="Local video path"><input value={path} onChange={e => setPath(e.target.value)} placeholder="Absolute path inside a configured import folder" /></Field>}</form>{browsing && <LocalFilePicker kind="video" onClose={() => setBrowsing(false)} onSelect={selected => { setPath(selected); setBrowsing(false); }} />}</Panel>
    <Panel title="Recordings" action={<span className="count">{detail.sources.length}</span>} className="source-list">{!detail.sources.length ? <Empty title="No source recordings yet">Import a video to inspect its metadata and define your first shot.</Empty> : <div className="select-list">{detail.sources.map(s => <button key={s.id} onClick={() => setSourceId(s.id)} className={`source-item ${source?.id === s.id ? 'selected' : ''}`}><span className="source-thumbnail"><Icon name="film" size={25} /></span><span><strong>{s.name}</strong><small>{s.width} × {s.height} · {fmt(s.duration)}</small><span className="tag">{s.is_vfr ? 'Variable frame rate' : `${Number(s.fps).toFixed(3)} fps`}</span></span><Icon name="arrow" size={16} /></button>)}</div>}</Panel>
    <Panel title={source?.name || 'Source preview'} subtitle="The original recording supplies timing, motion, and sound." className="source-preview">
      {source ? <><div className="video-stage">{previewFailed ? <img src={`/api/sources/${source.id}/frame?timestamp=${Math.min(start, source.duration - 0.001)}`} alt="Extracted original source frame at the in point" /> : <video key={source.id} ref={video} src={source.media_url} controls preload="metadata" playsInline onError={() => setPreviewFailed(true)} />}</div>{previewFailed && <div className="callout source-codec-note">This source codec cannot play in your browser. The extracted frame above follows the in point. Enter shot timestamps below; rendering uses the original media.</div>}<div className="metadata-grid"><div><span>DIMENSIONS</span><strong>{source.width} × {source.height}</strong></div><div><span>DURATION</span><strong>{fmt(source.duration)}</strong></div><div><span>FRAME RATE</span><strong>{Number(source.fps).toFixed(3)} fps {source.is_vfr && <em>VFR</em>}</strong></div><div><span>AUDIO</span><strong>{source.has_audio ? 'Original audio present' : 'No audio stream'}</strong></div></div><details className="technical-details"><summary>Source metadata & provenance</summary><dl><dt>Original path</dt><dd>{source.path}</dd><dt>SHA-256</dt><dd className="mono">{source.sha256}</dd><dt>Frame count</dt><dd>{source.frame_count ?? 'Not available'}</dd><dt>Display width</dt><dd>{source.display_width || source.width} px</dd></dl><pre>{JSON.stringify(source.metadata, null, 2)}</pre></details></> : <Empty title="A source preview will appear here">The app uses FFprobe to inspect dimensions, audio, frame rate, and field order.</Empty>}
    </Panel>
    <Panel title="Define a shot" subtitle="Begin with a short shot and limited movement." className="span-full">
      <form className="shot-form" onSubmit={createShot}><Field label="Shot name"><input value={name} onChange={e => setName(e.target.value)} placeholder={`Shot ${detail.shots.length + 1}`} /></Field><Field label="In point · seconds"><div className="input-action"><input type="number" min="0" max={source?.duration} step="0.001" value={start} onChange={e => setStart(Number(e.target.value))} /><button type="button" disabled={previewFailed} title="Use current video position as in point" onClick={() => setStart(Number((video.current?.currentTime || 0).toFixed(3)))}>Set</button></div></Field><Field label="Out point · seconds"><div className="input-action"><input type="number" min="0.001" max={source?.duration} step="0.001" value={end} onChange={e => setEnd(Number(e.target.value))} /><button type="button" disabled={previewFailed} title="Use current video position as out point" onClick={() => setEnd(Number((video.current?.currentTime || 0).toFixed(3)))}>Set</button></div></Field><button className="primary" disabled={busy || !source || end <= start || end > (source?.duration || 0)}>Create shot<Icon name="arrow" /></button></form><p className="field-hint">Use “Set” to take the current source playhead position. The out point is exclusive; timestamps and frame mapping are recorded.</p>
      {!!detail.shots.length && <div className="table-wrap"><table><thead><tr><th>SHOT</th><th>SOURCE</th><th>IN → OUT</th><th>FRAMES</th><th /></tr></thead><tbody>{detail.shots.map(s => <tr key={s.id}><td><strong>{s.name}</strong></td><td>{detail.sources.find(x => x.id === s.source_id)?.name}</td><td className="mono">{fmt(s.start_time)} → {fmt(s.end_time)}</td><td>{s.frame_end - s.frame_start}</td><td><button className="text-button" onClick={() => openShot(s.id)}>Set up shot<Icon name="arrow" size={15} /></button></td></tr>)}</tbody></table></div>}
    </Panel>
  </div>;
}

function ranking(reference: Reference, angle: string) { return (reference.approval_status === 'approved' ? 100 : reference.approval_status === 'pending' ? 0 : -100) + reference.quality * 5 + (reference.view === angle ? 10 : 0); }

function Actors({ detail, busy, act }: { detail: ProjectDetail; busy: boolean; act: Action }) {
  const [actorId, setActorId] = useState(detail.actors[0]?.id || '');
  const actor = detail.actors.find(a => a.id === actorId) || detail.actors[0];
  const [actorName, setActorName] = useState('');
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState('');
  const [mode, setMode] = useState<'path' | 'crop'>('path');
  const [browsing, setBrowsing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [imageInfo, setImageInfo] = useState<{ width: number; height: number; preview_url: string }>();
  const [imageError, setImageError] = useState('');
  useEffect(() => {
    let active = true; setImageInfo(undefined); setImageError('');
    if (mode !== 'path' || !path.trim() || !adding) return;
    const timer = setTimeout(() => { api<{ width: number; height: number; preview_url: string }>(`/files/image-info?path=${encodeURIComponent(path)}`).then(info => { if (active) setImageInfo(info); }).catch(e => { if (active) setImageError(e.message); }); }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [path, mode, adding]);
  const [applyCrop, setApplyCrop] = useState(false);
  const [sourceId, setSourceId] = useState(detail.sources[0]?.id || '');
  const [timestamp, setTimestamp] = useState(0);
  const [crop, setCrop] = useState({ x: 0, y: 0, width: 128, height: 128 });
  const [angle, setAngle] = useState<Reference['view']>('front');
  const [desiredAngle, setDesiredAngle] = useState('front');
  const [quality, setQuality] = useState(3);
  const [approval, setApproval] = useState('pending');
  const [provenance, setProvenance] = useState<Reference['provenance']>('external_photograph');
  const [expression, setExpression] = useState('');
  const [lighting, setLighting] = useState('');
  const [notes, setNotes] = useState('');
  async function addActor(e: FormEvent) { e.preventDefault(); await act(async () => { const item = await api<Actor>(`/projects/${detail.project.id}/actors`, { name: actorName }); setActorId(item.id); setActorName(''); }, 'Actor added. Import references and review their provenance.'); }
  async function addReference(e: FormEvent) { e.preventDefault(); if (!actor) return; await act(async () => { await api(`/actors/${actor.id}/references`, { ...(mode === 'path' ? { path, ...(applyCrop ? { crop: [crop.x, crop.y, crop.width, crop.height] } : {}) } : { source_id: sourceId, timestamp, crop: [crop.x, crop.y, crop.width, crop.height] }), view: angle, quality, approval_status: approval, provenance: mode === 'crop' && provenance !== 'generated_reconstruction' ? 'original_footage' : provenance, expression, lighting, notes }); setAdding(false); setPath(''); }, 'Reference imported with its provenance and approval status.'); }
  const references = detail.references.filter(r => r.actor_id === actor?.id).sort((a, b) => ranking(b, desiredAngle) - ranking(a, desiredAngle) || a.id.localeCompare(b.id));
  return <div className="actors-layout"><Panel title="Cast" action={<span className="count">{detail.actors.length}</span>}><div className="select-list">{detail.actors.map(a => <button key={a.id} className={`actor-item ${a.id === actor?.id ? 'selected' : ''}`} onClick={() => setActorId(a.id)}><span className="avatar">{a.name.slice(0, 2).toUpperCase()}</span><span><strong>{a.name}</strong><small>{detail.references.filter(r => r.actor_id === a.id && r.approval_status === 'approved').length} approved references</small></span></button>)}</div><form className="actor-form" onSubmit={addActor}><Field label="Add an actor"><input value={actorName} onChange={e => setActorName(e.target.value)} placeholder="Actor display name" required /></Field><button className="secondary full-width" disabled={busy || !actorName.trim()}><Icon name="plus" />Add actor</button></form></Panel>
    <div className="stack"><Panel title={actor ? `${actor.name} · references` : 'Actor references'} subtitle="Approval → quality → angle compatibility. Your selection stays fixed for the shot." action={actor && <button className="primary" onClick={() => setAdding(!adding)}><Icon name="plus" />Add reference</button>}>
      {adding && actor && <form className="reference-form" onSubmit={addReference}><div className="segmented"><button type="button" className={mode === 'path' ? 'active' : ''} aria-pressed={mode === 'path'} onClick={() => setMode('path')}>Image file</button><button type="button" className={mode === 'crop' ? 'active' : ''} aria-pressed={mode === 'crop'} onClick={() => { setMode('crop'); setProvenance(detail.project.demo_kind ? 'generated_reconstruction' : 'original_footage'); }}>Source-frame crop</button></div>{mode === 'path' ? <><div className="import-actions"><button type="button" className="secondary" onClick={event => { event.currentTarget.focus(); setBrowsing(true); }}>Browse local images</button><span className="selected-file">{path ? path.split(/[\\/]/).at(-1) : 'No image selected'}</span></div><label className="checkbox-field"><input type="checkbox" checked={advanced} onChange={e => setAdvanced(e.target.checked)} />Enter an advanced image path</label>{advanced && <Field label="Local image path"><input value={path} onChange={e => setPath(e.target.value)} placeholder="Absolute path inside a configured import folder" /></Field>}<label className="checkbox-field"><input type="checkbox" checked={applyCrop} onChange={e => setApplyCrop(e.target.checked)} />Crop this reference image</label>{imageError && <div className="callout amber" role="alert">{imageError}</div>}{imageInfo && <CropEditor key={`${path}-${applyCrop}`} src={imageInfo.preview_url} nativeSize={imageInfo} crop={crop} onChange={setCrop} enabled={applyCrop} />}</> : <><div className="form-grid"><Field label="Source recording"><select value={sourceId} onChange={e => setSourceId(e.target.value)} required><option value="">Select recording</option>{detail.sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field><Field label="Timestamp · seconds"><input type="number" step="0.001" min="0" max={detail.sources.find(s => s.id === sourceId)?.duration} value={timestamp} onChange={e => setTimestamp(Number(e.target.value))} /></Field></div>{sourceId && <CropEditor key={`${sourceId}-${timestamp}`} src={`/api/sources/${sourceId}/frame?timestamp=${timestamp}`} crop={crop} onChange={setCrop} />}</>}
      <div className="form-grid three"><Field label="View angle"><select value={angle} onChange={e => setAngle(e.target.value as Reference['view'])}><option value="front">Front</option><option value="three_quarter">Three-quarter</option><option value="profile">Profile</option></select></Field><Field label="Quality · 0–5"><input type="number" min="0" max="5" step="0.5" value={quality} onChange={e => setQuality(Number(e.target.value))} /></Field><Field label="Approval"><select value={approval} onChange={e => setApproval(e.target.value)}><option value="pending">Pending review</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></Field></div>
      {<Field label="Provenance"><select value={provenance} onChange={e => setProvenance(e.target.value as Reference['provenance'])}>{mode === 'path' && <option value="external_photograph">External photograph</option>}<option value="original_footage">Original footage</option><option value="generated_reconstruction">Generated reconstruction</option></select></Field>}<div className="form-grid"><Field label="Expression"><input value={expression} onChange={e => setExpression(e.target.value)} placeholder="Neutral, smiling, speaking…" /></Field><Field label="Lighting"><input value={lighting} onChange={e => setLighting(e.target.value)} placeholder="Soft front light, side light…" /></Field></div><Field label="Provenance / quality notes"><textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} placeholder="Where did this image come from? What should a reviewer know?" /></Field>{provenance === 'generated_reconstruction' && <div className="callout amber">Generated reconstructions remain labeled as generated, including after manual approval. They are not original evidence.</div>}<div className="button-row"><button type="button" className="secondary" onClick={() => setAdding(false)}>Cancel</button><button className="primary" disabled={busy || (mode === 'path' ? !path || !imageInfo : !sourceId)}>Import reference</button></div></form>}
      {!!references.length && <div className="ranking-toolbar"><span>{references.length} reference{references.length === 1 ? '' : 's'} · ranked for</span><select aria-label="Rank references for view angle" value={desiredAngle} onChange={e => setDesiredAngle(e.target.value)}><option value="front">Front view</option><option value="three_quarter">Three-quarter view</option><option value="profile">Profile view</option></select><small>Angle match +10 · quality ×5 · approval +100</small></div>}
      {!references.length ? <Empty icon="people" title={actor ? 'Build this actor’s reference library' : 'Add your first actor'}>Import an image or extract a crop from original footage. Review approval and provenance before using it.</Empty> : <div className="reference-grid">{references.map((r, index) => <article className="reference-card" key={r.id}><div className="reference-image"><img src={r.media_url} alt={`${actor?.name}, ${human(r.view)} reference`} /><span className="rank">#{index + 1}</span>{r.provenance === 'generated_reconstruction' && <span className="generated-tag">GENERATED</span>}</div><div className="reference-body"><div className="reference-top"><strong>{human(r.view)}</strong><span className="quality">{r.quality}/5</span></div><Status state={r.approval_status} /><p>{human(r.provenance)}</p>{r.expression && <p>Expression: {r.expression}</p>}{r.lighting && <p>Light: {r.lighting}</p>}{r.notes && <p className="reference-notes">{r.notes}</p>}<small className="mono" title={r.sha256}>{shortHash(r.sha256)}</small><label className="approval-control">Approval<select aria-label={`Approval for reference ${r.id}`} disabled={busy} value={r.approval_status} onChange={e => act(() => api(`/references/${r.id}`, { approval_status: e.target.value }, 'PATCH'), 'Reference approval updated. Existing render versions remain unchanged.')}><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label><details className="reference-provenance"><summary>Source & crop</summary><dl><dt>Source</dt><dd>{r.source_file || 'Not provided'}</dd>{r.timestamp !== undefined && <><dt>Timestamp</dt><dd>{fmt(r.timestamp)}</dd></>}{r.crop && <><dt>Crop · x, y, w, h</dt><dd>{r.crop.join(', ')}</dd></>}<dt>Reference SHA-256</dt><dd className="mono">{r.sha256}</dd>{r.original_hash && <><dt>Original SHA-256</dt><dd className="mono">{r.original_hash}</dd></>}</dl></details></div></article>)}</div>}
    </Panel>{browsing && <LocalFilePicker kind="image" onClose={() => setBrowsing(false)} onSelect={selected => { setPath(selected); setBrowsing(false); }} />}<div className="callout"><Icon name="info" /><span>References guide appearance and detail. They do not guarantee preservation of expression, gaze, blinking, or motion. Compare every candidate with the source.</span></div></div>
  </div>;
}

function placementAt(keyframes: Placement[], frame: number, interpolation: string): Placement | undefined {
  if (!keyframes.length) return undefined;
  const ordered = [...keyframes].sort((a, b) => a.frame - b.frame);
  const before = [...ordered].reverse().find(k => k.frame <= frame) || ordered[0];
  const after = ordered.find(k => k.frame >= frame) || ordered[ordered.length - 1];
  if (before.frame === after.frame || interpolation === 'hold') return { ...before, frame };
  const t = (frame - before.frame) / (after.frame - before.frame);
  return { frame, x: Math.round(before.x + (after.x - before.x) * t), y: Math.round(before.y + (after.y - before.y) * t), width: Math.round(before.width + (after.width - before.width) * t), height: Math.round(before.height + (after.height - before.height) * t) };
}

function ShotSetup({ detail, shot, setShotId, onDirtyChange, backends, busy, act, onQueued }: { detail: ProjectDetail; shot?: Shot; setShotId: (id: string) => void; onDirtyChange: (dirty: boolean) => void; backends: Backend[]; busy: boolean; act: Action; onQueued: () => void }) {
  const source = detail.sources.find(s => s.id === shot?.source_id);
  const [setup, setSetup] = useState<Setup>(shot?.setup || emptySetup);
  const [savedSetup, setSavedSetup] = useState(JSON.stringify(shot?.setup || emptySetup));
  const dirty = JSON.stringify(setup) !== savedSetup;
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  const [frame, setFrame] = useState(0);
  const [draft, setDraft] = useState<Placement>();
  const [guide, setGuide] = useState<Guide>();
  const [engine, setEngine] = useState('baseline');
  const [scale, setScale] = useState(2);
  const [seed, setSeed] = useState(42);
  const [prompt, setPrompt] = useState('Preserve the source performance, expression, gaze, and motion. Restore fine image detail.');
  const [useReferences, setUseReferences] = useState(false);
  const steps = 8;
  const [cfg, setCfg] = useState(1);
  const [angle, setAngle] = useState('front');
  const [presets, setPresets] = useState<Preset[]>([]);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const backend = backends.find(b => b.id === engine);
  const supportsReferences = backend?.supports_references || backend?.operations?.includes('static_spatial_reference');
  const movingPlacement = new Set(setup.keyframes.map(({ x, y, width, height }) => `${x},${y},${width},${height}`)).size > 1;
  useEffect(() => { setSetup(shot?.setup || emptySetup); setSavedSetup(JSON.stringify(shot?.setup || emptySetup)); setFrame(0); setDraft(undefined); setGuide(undefined); }, [shot?.id]);
  useEffect(() => { setGuide(undefined); }, [setup, engine, useReferences, scale]);
  useEffect(() => { api<Preset[]>('/presets').then(setPresets).catch(() => {}); }, []);
  function loadPreset(id: string) {
    const preset = presets.find(p => p.id === id);
    if (!preset) return;
    const settings = preset.settings;
    setEngine(settings.backend); setScale(settings.scale);
    if (settings.prompt !== undefined) setPrompt(settings.prompt);
    if (settings.seed !== undefined) setSeed(settings.seed);
    if (settings.cfg !== undefined) setCfg(settings.cfg);
    setUseReferences(settings.use_references || false); setGuide(undefined);
  }
  if (!shot || !source) return <Panel><Empty icon="frame" title="Select a source shot first">Create a shot in Sources & shots, then return here to place a face region and prepare a render.</Empty></Panel>;
  const maxFrame = Math.max(0, shot.frame_end - shot.frame_start - 1);
  const region = draft || placementAt(setup.keyframes, frame, setup.interpolation);
  const actorReferences = detail.references.filter(r => r.actor_id === setup.actor_id).sort((a, b) => ranking(b, angle) - ranking(a, angle) || a.id.localeCompare(b.id));
  function point(e: PointerEvent<HTMLDivElement>) { const box = e.currentTarget.getBoundingClientRect(); return { x: Math.max(0, Math.min(source!.width, (e.clientX - box.left) / box.width * source!.width)), y: Math.max(0, Math.min(source!.height, (e.clientY - box.top) / box.height * source!.height)) }; }
  function pointerDown(e: PointerEvent<HTMLDivElement>) { if (busy) return; e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = point(e); setDraft(undefined); }
  function pointerMove(e: PointerEvent<HTMLDivElement>) { if (busy || !drag.current) return; const p = point(e); setDraft({ frame, x: Math.round(Math.min(p.x, drag.current.x)), y: Math.round(Math.min(p.y, drag.current.y)), width: Math.round(Math.abs(p.x - drag.current.x)), height: Math.round(Math.abs(p.y - drag.current.y)) }); }
  function pointerUp(e: PointerEvent<HTMLDivElement>) { if (busy) { drag.current = null; setDraft(undefined); return; } if (!drag.current) return; const p = point(e); const next = { frame, x: Math.round(Math.min(p.x, drag.current.x)), y: Math.round(Math.min(p.y, drag.current.y)), width: Math.round(Math.abs(p.x - drag.current.x)), height: Math.round(Math.abs(p.y - drag.current.y)) }; drag.current = null; setDraft(undefined); if (next.width >= 4 && next.height >= 4) setSetup(prev => ({ ...prev, keyframes: [...prev.keyframes.filter(k => k.frame !== frame), next].sort((a, b) => a.frame - b.frame) })); }
  async function save() {
    // Freeze the submitted snapshot. The dirty effect compares it with the current
    // draft; a completed request must never clear changes made after submission.
    const submitted = setup; const serialized = JSON.stringify(submitted);
    await api(`/shots/${shot!.id}`, { setup: submitted }, 'PATCH');
    setSavedSetup(serialized);
  }
  async function makeGuide() { await act(async () => { await save(); setGuide(await api<Guide>(`/shots/${shot!.id}/guide`, { backend: engine, scale, use_references: engine !== 'baseline' && useReferences })); }, 'Guide prepared. Inspect the artifact before submitting a model job.'); }
  async function compareGroup() { await act(async () => { await save(); await api(`/shots/${shot!.id}/comparison`, { backend: engine, scale, prompt, seed, steps, cfg }); onQueued(); }, 'Controlled comparison queued: baseline, LTX without references, and the same LTX settings with references.'); }
  async function render() { await act(async () => { await save(); await api(`/shots/${shot!.id}/jobs`, { backend: engine, scale, prompt: engine === 'baseline' ? '' : prompt, seed, use_references: engine !== 'baseline' && useReferences, steps, cfg }); onQueued(); }, 'New render version queued. Start the worker if it is not running.'); }
  return <fieldset className="setup-layout setup-controls" disabled={busy} aria-label="Shot setup controls" aria-busy={busy}><div className="stack"><Panel title="Shot & placement" subtitle="Draw a face region in source coordinates. Add keyframes to correct movement." action={<select className="shot-select" aria-label="Select shot to set up" value={shot.id} onChange={e => setShotId(e.target.value)}>{detail.shots.map(s => <option value={s.id} key={s.id}>{s.name}</option>)}</select>}>
      <div className="placement-shell"><div className="placement-stage" style={{ aspectRatio: `${source.display_width || source.width} / ${source.height}` }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { drag.current = null; setDraft(undefined); }} role="img" aria-label="Source frame. Drag to draw a face region."><img src={`/api/shots/${shot.id}/frame?frame=${frame}`} alt={`Original source frame ${frame}`} draggable={false} />{region && <div className="placement-region" style={{ left: `${region.x / source.width * 100}%`, top: `${region.y / source.height * 100}%`, width: `${region.width / source.width * 100}%`, height: `${region.height / source.height * 100}%` }}><span>{detail.actors.find(a => a.id === setup.actor_id)?.name || 'Face region'}</span><i /><i /><i /><i /></div>}<span className="preview-chip">SOURCE FRAME · {frame}</span></div></div>
      <div className="frame-control"><button className="icon-button" disabled={frame === 0} onClick={() => setFrame(Math.max(0, frame - 1))} aria-label="Previous frame">←</button><input aria-label="Placement frame" type="range" min="0" max={maxFrame} step="1" value={frame} onChange={e => setFrame(Number(e.target.value))} /><button className="icon-button" disabled={frame >= maxFrame} onClick={() => setFrame(Math.min(maxFrame, frame + 1))} aria-label="Next frame">→</button><span className="mono">{fmt(shot.frame_map?.[frame]?.output_timestamp)} / {fmt(shot.duration)}</span></div>
      <div className="placement-meta"><span>{source.width} × {source.height} source px</span><span>Frame {frame} / {maxFrame}</span><span>{region ? `${region.x}, ${region.y} · ${region.width} × ${region.height}` : 'Drag to place a face region'}</span></div>
      <div className="manual-region"><div className="form-grid four">{(['x', 'y', 'width', 'height'] as const).map(k => <Field label={`${k} · px`} key={k}><input aria-label={`Face region ${k}`} type="number" min={k === 'width' || k === 'height' ? 1 : 0} max={k === 'x' || k === 'width' ? source.width : source.height} value={region?.[k] ?? 0} onChange={e => { const next = { frame, x: region?.x || 0, y: region?.y || 0, width: region?.width || 1, height: region?.height || 1, [k]: Number(e.target.value) }; setSetup(prev => ({ ...prev, keyframes: [...prev.keyframes.filter(p => p.frame !== frame), next].sort((a, b) => a.frame - b.frame) })); }} /></Field>)}</div></div>
      <div className="keyframe-head"><strong>Placement keyframes <span className="count">{setup.keyframes.length}</span></strong><select aria-label="Keyframe interpolation" value={setup.interpolation} onChange={e => setSetup({ ...setup, interpolation: e.target.value as Setup['interpolation'] })}><option value="linear">Linear interpolation</option><option value="hold">Hold placement</option></select></div><div className="keyframes">{!setup.keyframes.length ? <p className="muted">Draw a region or enter source pixel coordinates. The first region becomes a keyframe.</p> : setup.keyframes.map(k => <div className={`keyframe ${k.frame === frame ? 'current' : ''}`} key={k.frame}><button onClick={() => setFrame(k.frame)}><span className="keyframe-diamond">◆</span>Frame {k.frame}<small>{k.x}, {k.y} · {k.width} × {k.height}</small></button><button className="icon-button" aria-label={`Remove keyframe at frame ${k.frame}`} onClick={() => setSetup({ ...setup, keyframes: setup.keyframes.filter(p => p.frame !== k.frame) })}><Icon name="close" size={14} /></button></div>)}</div><div className="button-row"><button className="secondary" disabled={busy} onClick={() => act(save, 'Shot setup saved. Existing render versions remain unchanged.')}><Icon name="check" size={16} />{dirty ? 'Save setup · unsaved changes' : 'Save setup'}</button><button className="primary" disabled={busy || !setup.keyframes.length} onClick={makeGuide}>Prepare guide<Icon name="arrow" /></button></div>
    </Panel><Panel title="Guide artifact" subtitle="Inspect what has actually been prepared. Placement previews are labeled separately from model conditioning.">{guide ? <><div className="guide-stage">{guide.guide_url || guide.artifact_url ? <img src={guide.guide_url || guide.artifact_url} alt="Prepared face placement or model conditioning artifact" /> : <p>No image artifact was returned.</p>}</div><div className="guide-caption"><span className="tag">{guide.conditioning ? 'MODEL CONDITIONING ARTIFACT' : 'PLACEMENT PREVIEW'}</span><p>{guide.description || (engine === 'baseline' ? 'Review-only placement guide. The FFmpeg baseline does not use actor references.' : 'See the guide manifest for its conditioning mapping and supported use.')}</p></div>{guide.warnings?.map(w => <div className="callout amber" key={w}>{w}</div>)}<details className="technical-details"><summary>Coordinate transforms & guide manifest</summary><pre>{JSON.stringify(guide, null, 2)}</pre></details></> : <Empty icon="frame" title="Your guide is ready to prepare">Select an approved actor reference and place a region, then prepare the artifact for inspection.</Empty>}</Panel></div>
    <div className="stack"><Panel title="Actor & references" subtitle="One actor per shot in this first version."><div className="panel-body"><Field label="Assigned actor"><select value={setup.actor_id || ''} onChange={e => setSetup({ ...setup, actor_id: e.target.value || undefined, reference_ids: [] })}><option value="">No actor assigned</option>{detail.actors.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>{setup.actor_id && <><Field label="Rank for view angle"><select value={angle} onChange={e => setAngle(e.target.value)}><option value="front">Front</option><option value="three_quarter">Three-quarter</option><option value="profile">Profile</option></select></Field><div className="reference-choices">{actorReferences.length ? actorReferences.map(r => <label key={r.id} className={`reference-choice ${setup.reference_ids.includes(r.id) ? 'selected' : ''} ${r.approval_status !== 'approved' ? 'disabled' : ''}`}><input type="checkbox" disabled={r.approval_status !== 'approved'} checked={setup.reference_ids.includes(r.id)} onChange={e => setSetup({ ...setup, reference_ids: e.target.checked ? [r.id] : [] })} /><img src={r.media_url} alt={`${human(r.view)} actor reference`} /><span><strong>{human(r.view)} <small>{r.quality}/5</small></strong><small>{human(r.approval_status)} · {human(r.provenance)}</small></span></label>) : <p className="muted">Add this actor’s images in the Actor library.</p>}</div><p className="field-hint">Choose one approved reference for this first version. Selection stays fixed across the shot; generated provenance remains labeled.</p></>}</div></Panel>
      <Panel title="New render version" subtitle="Settings create a new job; previous outputs remain unchanged."><div className="panel-body">{!!presets.length && <Field label="Load preset" hint="Loads settings for review; no job is created."><select value="" onChange={e => loadPreset(e.target.value)}><option value="" disabled>Choose a preset…</option>{presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></Field>}<Field label="Render backend"><select value={engine} onChange={e => { setEngine(e.target.value); setGuide(undefined); }}>{backends.length ? backends.map(b => <option key={b.id} value={b.id}>{b.label}{!b.available ? ' · unavailable' : ''}</option>) : <option value="baseline">Baseline upscale</option>}</select></Field>{!backend?.available && <div className="callout amber">{backend?.reason || 'Backend availability has not been confirmed. Refresh or run doctor to inspect configuration.'}</div>}{engine === 'baseline' ? <div className="callout compact">Conventional FFmpeg upscale. No generative detail or actor-reference conditioning.</div> : <><Field label="Prompt"><textarea rows={4} value={prompt} onChange={e => setPrompt(e.target.value)} /></Field><Field label="Seed"><input type="number" min="0" max="4294967295" value={seed} onChange={e => setSeed(Number(e.target.value))} /></Field><label className="checkbox-field"><input type="checkbox" checked={useReferences} disabled={!supportsReferences} onChange={e => setUseReferences(e.target.checked)} />Use selected actor references</label><p className="field-hint">{supportsReferences ? 'Verified spatial reference mapping. The backend validates static placement before queueing.' : 'This backend has no available, verified actor-reference conditioning mapping.'}</p>{backend?.controls?.includes('steps') && <Field label="Sampling steps"><input type="number" value={steps} readOnly aria-label="Distilled workflow sampling steps (fixed)" /></Field>}{backend?.controls?.includes('cfg') && <Field label="CFG"><input type="number" min="0" max="20" step="0.1" value={cfg} onChange={e => setCfg(Number(e.target.value))} /></Field>}</>}
      {engine !== 'baseline' && useReferences && movingPlacement && <div className="callout amber">This backend requires a fixed spatial reference. Keep placement coordinates constant for reference-conditioned LTX rendering; moving keyframes can still be prepared for review.</div>}<Field label="Export scale" hint="Original aspect ratio is preserved; required working padding is recorded."><select value={scale} onChange={e => setScale(Number(e.target.value))}><option value={1}>1× · source dimensions</option><option value={2}>2× · {source.width * 2} × {source.height * 2}</option><option value={4}>4× · {source.width * 4} × {source.height * 4}</option></select></Field><div className="render-summary"><div><span>SHOT</span><strong>{shot.name}</strong></div><div><span>DURATION</span><strong>{fmt(shot.duration)}</strong></div><div><span>AUDIO</span><strong>{source.has_audio ? 'Original source audio' : 'Silent source'}</strong></div></div><button className="primary full-width" disabled={busy || !backend?.available || (useReferences && engine !== 'baseline' && (!supportsReferences || movingPlacement || !setup.reference_ids.length || !setup.keyframes.length))} onClick={render}>{busy ? 'Working…' : engine === 'baseline' ? 'Queue baseline upscale' : 'Queue LTX render'}<Icon name="arrow" /></button><button className="secondary full-width" disabled={busy || engine === 'baseline' || !backend?.available || !supportsReferences || movingPlacement || !setup.reference_ids.length || !setup.keyframes.length} onClick={compareGroup}>Queue A / B / C comparison</button><p className="field-hint">A: baseline · B: LTX without references · C: same LTX settings and seed with references. Select a configured LTX backend and approved references to enable.</p><p className="field-hint">One job runs at a time. LTX is never replaced with a baseline automatically.</p></div></Panel>
    </div></fieldset>;
}

function Queue({ detail, selectedJob, setJobId, busy, act, openJob, backends }: { detail: ProjectDetail; selectedJob?: Job; setJobId: (id: string) => void; busy: boolean; act: Action; openJob: (id: string) => void; backends: Backend[] }) {
  return <div className="queue-layout"><Panel title="Render versions" subtitle="Durable job states are updated by the separate worker." action={<span className="count">{detail.jobs.length}</span>}>{!detail.jobs.length ? <Empty icon="queue" title="The queue is clear">Create a shot and queue a baseline upscale from Shot setup to exercise the full local workflow.</Empty> : <div className="job-list">{[...detail.jobs].reverse().map(j => <button key={j.id} className={`job-item ${selectedJob?.id === j.id ? 'selected' : ''}`} onClick={() => setJobId(j.id)}><span className="job-number">V{String(j.version || detail.jobs.filter(x => x.shot_id === j.shot_id).indexOf(j) + 1).padStart(2, '0')}</span><span className="job-item-main"><strong>{detail.shots.find(s => s.id === j.shot_id)?.name || 'Shot'}</strong><small>{backends.find(b => b.id === j.backend)?.label || human(j.backend)}</small><span>{date(j.created_at)}</span></span><Status state={j.state} /></button>)}</div>}</Panel><Panel title="Job details" subtitle={selectedJob ? `Version ${selectedJob.version || '—'} · ${selectedJob.id}` : 'Select a render version to inspect it.'}>{selectedJob ? <><div className="job-detail-top"><Status state={selectedJob.state} /><Status state={selectedJob.review_state || 'unreviewed'} /></div>{selectedJob.state === 'running' && <div className="job-progress actual-stage"><span className="spinner" /><p>{human(selectedJob.progress_stage || 'processing')} · see worker logs for backend updates</p></div>}<div className="panel-body"><dl className="details-grid"><dt>Backend</dt><dd>{backends.find(b => b.id === selectedJob.backend)?.label || human(selectedJob.backend)}</dd><dt>Created</dt><dd>{date(selectedJob.created_at)}</dd><dt>Started</dt><dd>{date(selectedJob.started_at)}</dd><dt>Finished</dt><dd>{date(selectedJob.finished_at)}</dd><dt>Output</dt><dd>{selectedJob.output_url ? <a href={selectedJob.output_url} target="_blank" rel="noreferrer">Open rendered file ↗</a> : 'Available after a successful render'}</dd></dl>{selectedJob.error && <div className="callout amber"><strong>Job error</strong><p>{selectedJob.error}</p></div>}<div className="button-row">{['queued', 'running'].includes(selectedJob.state) && <button className="danger" disabled={busy} onClick={() => act(() => api(`/jobs/${selectedJob.id}/cancel`, {}), 'Cancellation requested. The worker records the final state.')}><Icon name="close" />Cancel job</button>}{['failed', 'canceled', 'interrupted'].includes(selectedJob.state) && <button className="secondary" disabled={busy} onClick={() => act(() => api(`/jobs/${selectedJob.id}/retry`, {}), 'A safe retry was queued as a new version.')}><Icon name="refresh" />Retry as new version</button>}{selectedJob.state === 'succeeded' && <button className="primary" onClick={() => openJob(selectedJob.id)}>Compare & review<Icon name="arrow" /></button>}</div></div><details className="technical-details" open={Boolean(selectedJob.error)}><summary>Worker logs</summary><pre>{Array.isArray(selectedJob.log) ? selectedJob.log.join('\n') : selectedJob.log || 'No log messages yet. Queued jobs require the background worker.'}</pre></details><details className="technical-details"><summary>Render provenance & technical integrity</summary><pre>{JSON.stringify(selectedJob.provenance || {}, null, 2)}</pre></details><div className="callout bottom-callout"><Icon name="info" /><span>A completed render has passed processing. Human review determines whether it preserves identity and performance.</span></div></> : <Empty icon="queue" title="No render selected">Settings, source and reference hashes, guides, timing, output paths, and technical checks are recorded with each version.</Empty>}</Panel></div>;
}

const criteriaNames = ['identity', 'eyes', 'mouth', 'expression', 'gaze', 'motion', 'flicker', 'invented_detail'];
function FaceCrop({ videoRef, exactImage, playing, source, region, time, label, pixelAspect = 1, failed = false }: { videoRef: RefObject<HTMLVideoElement | null>; exactImage?: HTMLImageElement; playing: boolean; source?: Source; region?: Placement; time: number; label: string; pixelAspect?: number; failed?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const video = videoRef.current; const target = canvas.current;
    if (!target || !region || !source) return;
    const draw = () => {
      const image = playing ? video : exactImage;
      if (!image || (image instanceof HTMLVideoElement && (image.readyState < 2 || !image.videoWidth))) return;
      const width = image instanceof HTMLVideoElement ? image.videoWidth : image.naturalWidth;
      const height = image instanceof HTMLVideoElement ? image.videoHeight : image.naturalHeight;
      if (!width || !height) return;
      const context = target.getContext('2d'); if (!context) return;
      const sx = width / source.width; const sy = height / source.height;
      // Crop coordinates remain coded source pixels. Correct only the displayed
      // crop's pixel aspect. Video natural dimensions already include SAR; raw
      // PNG dimensions do not, so apply this correction only to paused stills.
      target.width = Math.max(1, Math.round(region.width * sx * (playing ? 1 : pixelAspect)));
      target.height = Math.max(1, Math.round(region.height * sy));
      context.drawImage(image, region.x * sx, region.y * sy, region.width * sx, region.height * sy, 0, 0, target.width, target.height);
    };
    draw();
    if (!playing || !video) return;
    let active = true; let callback = 0;
    const onFrame = () => { if (!active) return; draw(); callback = video.requestVideoFrameCallback(onFrame); };
    if (typeof video.requestVideoFrameCallback === 'function') callback = video.requestVideoFrameCallback(onFrame);
    video.addEventListener('timeupdate', draw); video.addEventListener('seeked', draw); video.addEventListener('loadeddata', draw);
    return () => { active = false; if (callback && typeof video.cancelVideoFrameCallback === 'function') video.cancelVideoFrameCallback(callback); video.removeEventListener('timeupdate', draw); video.removeEventListener('seeked', draw); video.removeEventListener('loadeddata', draw); };
  }, [videoRef, exactImage, playing, source, region, time, pixelAspect]);
  return <div className="face-crop"><span>{label}</span>{!region ? <p>Place a face region in Shot setup to inspect a crop.</p> : playing || exactImage ? <canvas ref={canvas} aria-label={`${label} enlarged face region`} /> : <p>{failed ? 'Exact frame unavailable.' : 'Loading exact frame…'}</p>}</div>;
}

function Comparison({ detail, job, setJobId, busy, act }: { detail: ProjectDetail; job?: Job; setJobId: (id: string) => void; busy: boolean; act: Action }) {
  const completed = detail.jobs.filter(j => j.state === 'succeeded' && j.output_url);
  const selected = job?.state === 'succeeded' ? job : completed[completed.length - 1];
  const snapshot = selected?.provenance as { shot?: Shot; source?: Source; references?: Reference[]; output_metadata?: { width: number; height: number; sar?: number }; settings?: { use_references: boolean } } | undefined;
  const shot = snapshot?.shot || detail.shots.find(s => s.id === selected?.shot_id);
  const liveSource = detail.sources.find(s => s.id === shot?.source_id);
  const source = snapshot?.source ? { ...liveSource, ...snapshot.source } as Source : liveSource;
  const savedReferences = snapshot?.references || detail.references;
  const original = useRef<HTMLVideoElement>(null);
  const output = useRef<HTMLVideoElement>(null);
  const [mode, setMode] = useState<'side' | 'overlay'>('side');
  const [opacity, setOpacity] = useState(0.5);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  const endedRef = useRef(false);
  const timeRef = useRef(0);
  const [sourceDuration, setSourceDuration] = useState(0);
  const [outputDuration, setOutputDuration] = useState(0);
  const [notes, setNotes] = useState('');
  const [criteria, setCriteria] = useState<Record<string, string>>({});
  const [muted, setMuted] = useState(false);
  const [playheadDrift, setPlayheadDrift] = useState<number | null>(null);
  useEffect(() => { const lastReview = selected?.reviews?.at(-1); timeRef.current = 0; setTime(0); endedRef.current = false; playingRef.current = false; setPlaying(false); setNotes(lastReview?.notes || ''); setCriteria(lastReview?.criteria || {}); setSourceDuration(0); setOutputDuration(0); setPlayheadDrift(null); }, [selected?.id]);
  const sourceOffset = selected?.source_preview_url ? 0 : shot?.start_time || 0;
  const duration = outputDuration || shot?.duration || 0;
  const syncThreshold = Math.min(0.02, 0.5 / (source?.fps || 25));
  useEffect(() => {
    const a = original.current; const b = output.current;
    if (!a || !b) return;
    let active = true;
    let callback = 0;
    const measure = () => {
      if (playingRef.current && !b.paused && a.readyState >= 2 && b.readyState >= 2) setPlayheadDrift(a.currentTime - sourceOffset - b.currentTime);
    };
    const onFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
      if (!active) return;
      // Output is the master clock. Seek the source only after its prior seek has
      // finished, so slower decoding cannot create an unbounded seek queue.
      if (playingRef.current && !b.paused) {
        if (!a.seeking && Math.abs(a.currentTime - sourceOffset - b.currentTime) > syncThreshold) a.currentTime = sourceOffset + b.currentTime;
        timeRef.current = metadata.mediaTime; setTime(metadata.mediaTime); measure();
      }
      callback = b.requestVideoFrameCallback(onFrame);
    };
    if (typeof b.requestVideoFrameCallback === 'function') callback = b.requestVideoFrameCallback(onFrame);
    a.addEventListener('seeked', measure); b.addEventListener('seeked', measure);
    return () => {
      active = false;
      if (callback && typeof b.cancelVideoFrameCallback === 'function') b.cancelVideoFrameCallback(callback);
      a.removeEventListener('seeked', measure); b.removeEventListener('seeked', measure);
      a.pause(); b.pause();
    };
  }, [selected?.id, sourceOffset, syncThreshold]);
  const localFrame = shot?.frame_map ? [...shot.frame_map].reverse().find(f => f.output_timestamp <= time + 0.000001)?.frame || 0 : Math.max(0, Math.min((shot?.frame_end || 1) - (shot?.frame_start || 0) - 1, Math.floor(time * (source?.fps || 1) + 0.000001)));
  const exact = useExactFrames(selected?.id, localFrame, !playing);
  const sourcePixelAspect = source?.sar || (source?.display_width ? source.display_width / source.width : 1);
  const outputPixelAspect = snapshot?.output_metadata?.sar || 1;
  const sourceDisplayAspect = source ? source.width * sourcePixelAspect / source.height : 1;
  const outputDisplayAspect = snapshot?.output_metadata ? snapshot.output_metadata.width * outputPixelAspect / snapshot.output_metadata.height : sourceDisplayAspect;
  const region = shot && source ? placementAt(shot.setup?.keyframes || [], localFrame, shot.setup?.interpolation || 'linear') : undefined;
  function canonicalTime(next: number) {
    const mapping = shot?.frame_map;
    if (mapping?.length) return [...mapping].reverse().find(entry => entry.output_timestamp <= next + 0.000001)?.output_timestamp || 0;
    const fps = source?.fps || 25;
    const last = Math.max(0, (shot?.frame_end || 1) - (shot?.frame_start || 0) - 1);
    return Math.max(0, Math.min(last, Math.floor(next * fps + 0.000001))) / fps;
  }
  function sync(next: number) {
    endedRef.current = false;
    const target = playingRef.current ? next : canonicalTime(next);
    timeRef.current = target; setTime(target);
    if (original.current) original.current.currentTime = target + sourceOffset;
    if (output.current) output.current.currentTime = target;
  }
  function pauseTogether() {
    if (!playingRef.current) return; // A paused browser seek is not a new playhead.
    const current = output.current?.currentTime ?? timeRef.current;
    const ended = !!output.current?.ended || (!!output.current?.duration && current >= output.current.duration - 0.000001);
    playingRef.current = false; setPlaying(false);
    original.current?.pause(); output.current?.pause(); sync(current); endedRef.current = ended;
  }
  function finishPlayback() { pauseTogether(); endedRef.current = true; }
  async function togglePlay() {
    const a = original.current; const b = output.current; if (!a || !b) return;
    if (playingRef.current) { pauseTogether(); return; }
    const next = endedRef.current || timeRef.current >= duration - 0.02 ? 0 : timeRef.current;
    exact.clear(); sync(next); playingRef.current = true; setPlaying(true);
    try { await Promise.all([a.play(), b.play()]); } catch { pauseTogether(); }
  }
  function stepFrame(direction: -1 | 1) {
    const current = playingRef.current ? output.current?.currentTime ?? timeRef.current : timeRef.current;
    playingRef.current = false; setPlaying(false); original.current?.pause(); output.current?.pause();
    const mapping = shot?.frame_map;
    if (mapping?.length) {
      let index = 0;
      mapping.forEach((entry, i) => { if (entry.output_timestamp <= current + 0.000001) index = i; });
      sync(mapping[Math.max(0, Math.min(mapping.length - 1, index + direction))].output_timestamp);
    } else sync(canonicalTime(current) + direction / (source?.fps || 25));
  }
  function updateTime() {
    const a = original.current; const b = output.current;
    if (!a || !b || !playingRef.current || b.paused || typeof b.requestVideoFrameCallback === 'function') return;
    timeRef.current = b.currentTime; setTime(b.currentTime);
    if (!a.seeking && Math.abs(a.currentTime - sourceOffset - b.currentTime) > syncThreshold) a.currentTime = sourceOffset + b.currentTime;
    setPlayheadDrift(a.currentTime - sourceOffset - b.currentTime);
  }
  async function review(state: string) { if (!selected) return; await act(() => api(`/jobs/${selected.id}/review`, { state, notes, criteria }), `Review saved: ${human(state)}. The rendered file remains unchanged.`); }
  async function addNote() { if (!shot) return; await act(async () => { await api(`/projects/${detail.project.id}/notes`, { shot_id: shot.id, actor_id: shot.setup?.actor_id, timestamp: shot.start_time + time, text: notes }); setNotes(''); }, 'Timestamped source note saved.'); }
  if (!selected || !shot || !source) return <Panel><Empty icon="compare" title="Your first comparison starts with a render">Queue a conventional baseline upscale to review source and output together. Successful LTX renders appear here with their exact backend label.</Empty></Panel>;
  const alignmentDifference = sourceDuration && outputDuration ? outputDuration - (selected.source_preview_url ? sourceDuration : shot.duration) : undefined;
  const baseline = selected.backend === 'baseline';
  const conditioningLabel = snapshot?.settings?.use_references ? 'actor reference conditioned' : 'no actor reference conditioning';
  return <div className="comparison-layout"><Panel className="span-full" title={shot.name} subtitle={`${baseline ? 'Baseline upscale' : human(selected.backend)} · ${conditioningLabel} · version ${selected.version || '—'} · review ${human(selected.review_state || 'unreviewed')}`} action={<div className="comparison-actions"><select aria-label="Render version to compare" value={selected.id} onChange={e => setJobId(e.target.value)}>{completed.map(j => <option key={j.id} value={j.id}>{detail.shots.find(s => s.id === j.shot_id)?.name} · {human(j.backend)} · v{j.version || j.id.slice(0, 5)}</option>)}</select><div className="segmented"><button className={mode === 'side' ? 'active' : ''} aria-pressed={mode === 'side'} onClick={() => setMode('side')}>Side by side</button><button className={mode === 'overlay' ? 'active' : ''} aria-pressed={mode === 'overlay'} onClick={() => setMode('overlay')}>Overlay</button></div></div>}>
    <div className={`comparison-stage ${mode} ${playing ? 'playing' : 'paused'}`} data-frame={localFrame} data-frame-ready={!playing && !!exact.pair ? 'true' : 'false'} tabIndex={0} role="group" aria-label="Synchronized comparison. Left and right arrows step frames; Space plays or pauses." onKeyDown={event => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); stepFrame(event.key === 'ArrowLeft' ? -1 : 1); } else if (event.key === ' ' && !event.repeat) { event.preventDefault(); void togglePlay(); } }} style={{ '--overlay-opacity': opacity } as CSSProperties}>
      <div className="compare-video original" style={{ '--frame-aspect': sourceDisplayAspect } as CSSProperties}><span className="preview-chip">ORIGINAL SOURCE{!playing && exact.pair ? ` · FRAME ${localFrame}` : ''}</span><video className={playing ? '' : 'hidden-for-still'} key={`source-${selected.id}`} ref={original} src={selected.source_preview_url || source.media_url} muted playsInline preload="auto" onLoadedMetadata={() => { setSourceDuration(original.current?.duration || 0); if (original.current) original.current.currentTime = sourceOffset + timeRef.current; }} />{!playing && (exact.pair ? <img className="exact-frame" src={exact.pair.source.url} alt="Original source paused frame" data-frame={localFrame} /> : <div className="still-placeholder">{exact.failed ? 'Original frame unavailable' : `Loading original frame ${localFrame}…`}</div>)}</div>
      <div className="compare-video output" style={{ '--frame-aspect': outputDisplayAspect } as CSSProperties}><span className="preview-chip">{baseline ? 'BASELINE UPSCALE' : 'LTX CANDIDATE'} · V{selected.version || '—'}{!playing && exact.pair ? ` · FRAME ${localFrame}` : ''}</span><video className={playing ? '' : 'hidden-for-still'} key={selected.id} ref={output} src={selected.output_url} muted={muted} playsInline preload="auto" onLoadedMetadata={() => setOutputDuration(output.current?.duration || 0)} onTimeUpdate={updateTime} onEnded={finishPlayback} onPause={pauseTogether} />{!playing && (exact.pair ? <img className="exact-frame" src={exact.pair.output.url} alt="Rendered output paused frame" data-frame={localFrame} /> : <div className="still-placeholder">{exact.failed ? 'Output frame unavailable' : `Loading output frame ${localFrame}…`}</div>)}</div>
    </div>{!playing && !exact.pair && <div className={`exact-frame-status ${exact.failed ? 'failed' : ''}`} role={exact.failed ? 'alert' : 'status'}>{exact.failed ? <><span>Exact paused frames could not be loaded. Check that the version’s source and output files are unchanged and available.</span><button className="secondary" onClick={exact.retry}>Retry exact frames</button></> : `Loading exact comparison frame ${localFrame}…`}</div>}

    <div className="playback"><button className="play-button" aria-label={playing ? 'Pause synchronized playback' : 'Play synchronized comparison'} onClick={togglePlay}><Icon name={playing ? 'pause' : 'play'} size={17} /></button><button className="frame-step" aria-label="Previous comparison frame" title="Previous frame" onClick={() => stepFrame(-1)}>‹</button><button className="frame-step" aria-label="Next comparison frame" title="Next frame" onClick={() => stepFrame(1)}>›</button><span className="mono">{fmt(time)}</span><input aria-label="Synchronized comparison playhead" type="range" min="0" max={duration || 1} step="0.001" value={Math.min(time, duration)} onChange={e => sync(Number(e.target.value))} /><span className="mono">{fmt(duration)}</span><button className="audio-toggle" onClick={() => setMuted(!muted)}>{muted ? 'Audio off' : 'Original audio'}</button></div>{mode === 'overlay' && <div className="overlay-control"><span>Source</span><input aria-label="Output overlay opacity" type="range" min="0" max="1" step="0.01" value={opacity} onChange={e => setOpacity(Number(e.target.value))} /><span>Output · {Math.round(opacity * 100)}%</span></div>}
    <p className="comparison-keyboard-hint">Focus the video area: ← / → step one frame · Space plays or pauses. Paused views decode the exact stored frame from each file.</p><div className="alignment-bar"><span className={playing && playheadDrift !== null && Math.abs(playheadDrift) > syncThreshold ? 'alignment-warning' : ''}><span className="dot" />{playing ? 'Live playhead drift' : 'Paused comparison'} <strong>{!playing ? exact.pair ? `exact frame ${localFrame}` : exact.failed ? 'unavailable' : 'loading…' : playheadDrift === null ? 'loading…' : `${playheadDrift >= 0 ? '+' : ''}${(playheadDrift * 1000).toFixed(1)} ms`}</strong></span><span>Duration difference <strong>{alignmentDifference === undefined ? 'loading…' : `${alignmentDifference >= 0 ? '+' : ''}${(alignmentDifference * 1000).toFixed(1)} ms`}</strong></span><span>Source timestamp <strong className="mono">{fmt(shot.start_time + time)}</strong></span></div>
  </Panel><div className="stack"><Panel title="Look closer" subtitle="Enlarged regions follow the manually placed face keyframes."><div className="face-grid"><FaceCrop videoRef={original} exactImage={exact.pair?.source.image} playing={playing} pixelAspect={sourcePixelAspect} failed={exact.failed} source={source} region={region} time={time} label="Original face" /><FaceCrop videoRef={output} exactImage={exact.pair?.output.image} playing={playing} pixelAspect={outputPixelAspect} failed={exact.failed} source={source} region={region} time={time} label="Rendered face" /></div><div className="selected-references"><span className="eyebrow">SELECTED ACTOR REFERENCES</span><div>{(shot.setup?.reference_ids || []).map(id => savedReferences.find(r => r.id === id)).filter((r): r is Reference => !!r).map(r => <figure key={r.id}><img src={r.media_url || (r.asset_path ? `/api/assets/${encodeURI(r.asset_path)}` : detail.references.find(current => current.id === r.id)?.media_url)} alt={`${human(r.view)} reference`} /><figcaption>{human(r.view)}{r.provenance === 'generated_reconstruction' && <b>Generated</b>}</figcaption></figure>)}{!shot.setup?.reference_ids?.length && <p className="muted">This shot has no selected actor references.</p>}</div></div></Panel><Panel title="Technical integrity" subtitle="Processing checks do not establish identity or performance fidelity."><div className="panel-body"><dl className="details-grid"><dt>Source timing</dt><dd>{fmt(shot.start_time)} → {fmt(shot.end_time)}</dd><dt>Source frames</dt><dd>{shot.frame_start} → {shot.frame_end} (exclusive)</dd><dt>Source aspect ratio</dt><dd>{source.display_width || source.width} : {source.height}</dd><dt>Audio policy</dt><dd>Original source audio by default</dd><dt>Review status</dt><dd><Status state={selected.review_state || 'unreviewed'} /></dd></dl></div><details className="technical-details"><summary>Recorded render manifest & checks</summary><pre>{JSON.stringify(selected.provenance || {}, null, 2)}</pre></details></Panel>
      {!!detail.notes.filter(n => n.shot_id === shot.id).length && <Panel title="Shot notes"><div className="saved-notes">{detail.notes.filter(n => n.shot_id === shot.id).map(n => <article key={n.id}><span className="mono">{n.timestamp === undefined ? 'Shot note' : fmt(n.timestamp)}</span><p>{n.text}</p></article>)}</div></Panel>}
    </div><Panel title="Performance review" subtitle="Judge the candidate against the original performance. No accuracy score is inferred."><div className="panel-body"><div className="review-criteria">{criteriaNames.map(name => <label key={name}><span>{human(name)}</span><select aria-label={`${human(name)} review criterion`} value={criteria[name] || 'unreviewed'} onChange={e => setCriteria({ ...criteria, [name]: e.target.value })}><option value="unreviewed">Not reviewed</option><option value="preserved">Looks preserved</option><option value="concern">Concern / revise</option></select></label>)}</div><Field label={`Review notes · source ${fmt(shot.start_time + time)}`}><textarea rows={5} placeholder="Check eye and mouth shape, expression, gaze, blinking, motion, consistency, and invented detail…" value={notes} onChange={e => setNotes(e.target.value)} /></Field><button className="text-button note-button" disabled={busy || !notes.trim()} onClick={addNote}><Icon name="plus" size={15} />Save a timestamped note</button><div className="review-actions"><button className="primary" disabled={busy} onClick={() => review('accepted')}><Icon name="check" />Accept version</button><button className="secondary" disabled={busy} onClick={() => review('needs_revision')}>Needs revision</button><button className="danger" disabled={busy} onClick={() => review('rejected')}><Icon name="close" />Reject</button></div><p className="field-hint">Acceptance records your judgment. This version’s file stays unchanged; settings changes require a new render.</p></div></Panel></div>;
}
