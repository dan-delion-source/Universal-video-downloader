import { useEffect, useRef, useState } from 'preact/hooks';
import { api, watchJob, fileUrl } from './api';
import Icon from './components/Icon';
import UrlForm from './components/UrlForm';
import MediaCard from './components/MediaCard';
import Toast from './components/Toast';
import AdvancedBrowser from './components/AdvancedBrowser';

function initialTheme() { try { return localStorage.getItem('uvd-theme') || 'light'; } catch { return 'light'; } }
export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const [health, setHealth] = useState(null);
  const [offline, setOffline] = useState(false);
  const [items, setItems] = useState([]);
  const [phase, setPhase] = useState('idle');
  const [page, setPage] = useState('');
  const [warnings, setWarnings] = useState([]);
  const [jobs, setJobs] = useState({});
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState({});
  const [updating, setUpdating] = useState(false);
  const [toast, setToast] = useState(null);
  const [view, setView] = useState('find');
  const [batch, setBatch] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [browserUrl, setBrowserUrl] = useState('');
  const streams = useRef({});
  const pending = useRef(new Set());
  const scanController = useRef();
  const resultRef = useRef();
  const notify = (message, error = false) => setToast({ message, error });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('uvd-theme', theme); } catch {}
  }, [theme]);
  useEffect(() => {
    api('/health').then(setHealth).catch(() => setOffline(true));
    api('/jobs').then(data => {
      setHistory(data.jobs);
      data.jobs.filter(j => !['complete', 'cancelled', 'error'].includes(j.status)).forEach(j => subscribe(j.id));
    }).catch(() => {});
    return () => { Object.values(streams.current).forEach(close => close()); scanController.current?.abort(); };
  }, []);
  useEffect(() => { if (!toast || toast.error) return; const timer = setTimeout(() => setToast(null), 6000); return () => clearTimeout(timer); }, [toast]);
  const applyEvent = event => {
    setJobs(previous => ({ ...previous, [event.id]: event }));
    setHistory(previous => [event, ...previous.filter(j => j.id !== event.id)].sort((a, b) => b.created_at - a.created_at));
    if (event.status === 'error') notify(event.error || 'Download failed. Try scanning again.', true);
    if (['complete', 'error', 'cancelled'].includes(event.status)) delete streams.current[event.id];
  };
  function subscribe(id) {
    streams.current[id] = watchJob(id, applyEvent, () => notify('Progress connection closed. Check Downloads for the latest status.', true));
  }
  const scan = async url => {
    if (phase === 'scanning') return;
    setPhase('scanning'); setItems([]); setWarnings([]); setPage(url); setToast(null);
    scanController.current = new AbortController();
    try {
      const result = await api('/scan', { url }, scanController.current.signal);
      setItems(result.items); setWarnings(result.warnings || []); setPhase(result.items.length ? 'results' : 'empty');
      requestAnimationFrame(() => resultRef.current?.focus());
    } catch (error) { if (error.name !== 'AbortError') { setPhase('error'); notify(error.message, true); } }
  };
  const openBrowser = url => { setPage(url); setBrowserUrl(url); };
  const browserMedia = (found, sessionId) => {
    if (!found.length) return;
    setItems(previous => {
      const merged = new Map(previous.map(item => [item.id, item]));
      for (const item of found) merged.set(item.id, { ...merged.get(item.id), ...item, browser_session_id: sessionId });
      return [...merged.values()].slice(-80);
    });
    setPhase('results');
  };
  const download = async (item, quality = 'best') => {
    if (pending.current.has(item.id)) return;
    pending.current.add(item.id); setBusy(previous => ({ ...previous, [item.id]: true }));
    try {
      const { job_id } = await api('/download', { url: item.download_target, format_id: quality, title: item.title, ...(item.browser_session_id ? { browser_session_id: item.browser_session_id } : {}) });
      setItems(previous => previous.map(x => x.id === item.id ? { ...x, jobId: job_id } : x));
      applyEvent({ id: job_id, title: item.title, status: 'queued', percent: 0, created_at: Date.now() / 1000 });
      subscribe(job_id);
    } catch (error) { notify(error.message, true); }
    finally { pending.current.delete(item.id); setBusy(previous => ({ ...previous, [item.id]: false })); }
  };
  const cancel = async id => { try { await api(`/jobs/${id}/cancel`, {}); } catch (error) { notify(error.message, true); } };
  const downloadAll = async () => {
    setBatch(true);
    for (const item of items.filter(x => !x.drm && !['queued', 'downloading', 'merging', 'complete'].includes(jobs[x.jobId]?.status))) await download(item);
    setBatch(false);
  };
  const update = async () => {
    setUpdating(true);
    try { const result = await api('/update-engine', {}); setHealth(previous => ({ ...previous, ...result })); notify(`Engine updated to ${result.ytdlp_version}.`); }
    catch (error) { notify(error.message, true); }
    finally { setUpdating(false); }
  };
  const active = history.filter(j => ['queued', 'downloading', 'merging'].includes(j.status)).length;
  const downloadable = items.filter(x => !x.drm).length;
  return <div className="app-shell">
    <header className="header"><a className="brand" href="/" aria-label="Universal Video Downloader home"><span className="brand-icon"><Icon name="download" size={22}/></span><span>Universal<span className="brand-description">Video Downloader</span></span></a>
      <nav aria-label="Main navigation"><button className={`nav-button ${view === 'find' ? 'selected' : ''}`} onClick={() => setView('find')}>Find videos</button><button className={`nav-button ${view === 'downloads' ? 'selected' : ''}`} onClick={() => { setView('downloads'); api('/jobs').then(x => setHistory(x.jobs)).catch(e => notify(e.message, true)); }}>Downloads{active > 0 && <span className="count">{active}</span>}</button></nav>
      <div className="header-tools"><span className={`local-status ${offline ? 'offline' : ''}`}><span/>{offline ? 'Server unavailable' : health ? 'Running locally' : 'Connecting'}</span><button className="theme-button" aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}><Icon name={theme === 'light' ? 'moon' : 'sun'}/></button></div>
    </header>
    <main>
      {offline && <p className="notice error-notice" role="alert">Cannot reach the API. Start the app with <code>python run.py</code>, then reload this page.</p>}
      {health && !health.ffmpeg && <p className="notice" role="status">ffmpeg is missing. Combined video and audio formats are available; install ffmpeg for the highest quality.</p>}
      {view === 'find' ? <>
        <section className="workspace" aria-labelledby="page-title"><div className="intro"><h1>A link. A video.<br/><span>Yours to keep.</span></h1><p>Find the videos on a page. Choose your quality.<br className="desktop-break"/> Save them straight to your device.</p></div>
          <UrlForm onScan={advanced ? openBrowser : scan} scanning={phase === 'scanning'} disabled={updating || Boolean(browserUrl)} advanced={advanced} onAdvanced={setAdvanced}/>
          <div className="trust-line"><span><Icon name="shield" size={16}/>Local & private</span><span><Icon name="check" size={16}/>Best available quality</span><span><Icon name="folder" size={16}/>No accounts. No cloud.</span></div>
        </section>
        <section className="results-section" aria-labelledby="results-title"><div className="section-heading"><div><h2 id="results-title" ref={resultRef} tabIndex={-1}>{phase === 'idle' ? 'Your next video starts here' : phase === 'scanning' ? 'Looking for videos…' : phase === 'results' ? `Found ${items.length} video${items.length === 1 ? '' : 's'}` : phase === 'empty' ? 'No videos found' : 'This page couldn’t be scanned'}</h2>{phase === 'results' && <p className="page-source" title={page}>{page}</p>}</div>{downloadable > 1 && phase === 'results' && <button className="button secondary" onClick={downloadAll} disabled={batch || updating}><Icon name="download" size={17}/>{batch ? 'Adding downloads…' : 'Download all (best)'}</button>}</div>
          {warnings.map(warning => <p className="scan-warning" key={warning}>{warning}</p>)}
          {phase === 'idle' && <div className="empty-state"><div className="empty-icon"><Icon name="link" size={30}/></div><h3>Bring the link. We’ll find the video.</h3><p>Paste a link above to see available videos and quality options.</p><div className="supported"><span>Video pages</span><span>Playlists</span><span>Direct video links</span></div></div>}
          {phase === 'scanning' && <div className="media-grid" aria-busy="true" aria-label="Scanning for videos">{[0, 1, 2].map(i => <div className="skeleton" key={i}><div/><span/><span/><span/></div>)}<p className="sr-only">Scanning the page. This can take up to 65 seconds.</p></div>}
          {phase === 'results' && <div className="media-grid">{items.map((item, index) => <MediaCard key={item.id} item={item} index={index} job={jobs[item.jobId]} busy={busy[item.id] || updating} onDownload={download} onCancel={cancel} onView={() => openBrowser(item.page_url || page || item.download_target)}/>)}</div>}
          {['empty', 'error'].includes(phase) && <div className="empty-state"><div className="empty-icon"><Icon name="search" size={30}/></div><h3>{phase === 'empty' ? 'Try the original video page' : 'Let’s try another link'}</h3><p>{phase === 'empty' ? 'Some sites hide their videos or require a sign-in. Try a direct video URL or enable the optional browser scanner.' : 'Check the link and your connection, then scan again. Updating the engine can help with supported sites.'}</p></div>}
        </section>
      </> : <section className="downloads-section"><div className="section-heading"><div><h1>Your downloads</h1><p>Recent jobs from this session. Completed files stay on your device.</p></div><span className="subtle">{history.length} total</span></div>
        {!history.length ? <div className="empty-state"><div className="empty-icon"><Icon name="folder" size={30}/></div><h3>A little room for your collection.</h3><p>Your downloads will appear here once you save your first video.</p><button className="button secondary" onClick={() => setView('find')}>Find a video<Icon name="arrow" size={17}/></button></div> : <div className="history-list">{history.map(job => <article className="history-row" key={job.id}><div className="history-icon"><Icon name={job.status === 'complete' ? 'check' : 'download'} size={22}/></div><div className="history-copy"><h2>{job.title}</h2><p>{job.status === 'complete' ? 'Ready to save' : job.status === 'downloading' ? `Downloading · ${Math.round(job.percent)}%` : job.status === 'merging' ? 'Preparing your file' : job.status === 'error' ? job.error : job.status}</p></div>{job.status === 'complete' ? <a className="button secondary" href={fileUrl(job.filename)} download><Icon name="download" size={16}/>Save file</a> : ['queued', 'downloading', 'merging'].includes(job.status) ? <button className="button secondary" onClick={() => cancel(job.id)}>Cancel</button> : null}</article>)}</div>}
      </section>}
      <aside className="engine-bar"><div><span className="engine-symbol"><Icon name="play" size={19}/></span><div><strong>Powered by yt-dlp</strong><span>{health ? `Engine ${health.ytdlp_version}` : 'Checking engine…'}<span className="engine-divider">·</span>{health?.ffmpeg ? 'ffmpeg ready' : health ? 'ffmpeg not installed' : 'Local video extraction'}</span></div></div><button className="text-button" disabled={updating || active > 0 || phase === 'scanning' || Boolean(browserUrl)} onClick={update}><Icon name="refresh" size={15} className={updating ? 'spin' : ''}/>{updating ? 'Updating…' : 'Update engine'}</button></aside>
    </main>
    <footer><span>Made for your own corner of the internet.</span><span>Save only what you own or have permission to download. DRM is unsupported.</span></footer>
    {browserUrl && <AdvancedBrowser url={browserUrl} onClose={() => setBrowserUrl('')} onDetected={browserMedia} items={items} jobs={jobs} busy={busy} onDownload={download} onCancel={cancel} toast={toast} dismissToast={() => setToast(null)}/>}
    {!browserUrl && <Toast toast={toast} dismiss={() => setToast(null)}/>}
  </div>;
}
