import { useEffect, useRef, useState } from 'preact/hooks';
import { api } from '../api';
import Icon from './Icon';
import MediaCard from './MediaCard';
import Toast from './Toast';

export default function AdvancedBrowser({ url, onClose, onDetected, items, jobs, busy, onDownload, onCancel, toast, dismissToast }) {
  const [state, setState] = useState({ status: 'starting', items: [], tabs: [], popups: [] });
  const [error, setError] = useState('');
  const [address, setAddress] = useState(url);
  const [frame, setFrame] = useState('');
  const dialog = useRef();
  const id = useRef();
  const notify = useRef(onDetected);
  const preview = useRef();
  const version = useRef(0);
  const signature = useRef('');
  const closing = useRef(false);
  const commandQueue = useRef(Promise.resolve());
  notify.current = onDetected;

  useEffect(() => {
    let disposed = false;
    let timer;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current.showModal();
    const release = () => {
      if (id.current) fetch(`/api/browser/sessions/${id.current}/close`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', keepalive: true,
      }).catch(() => {});
    };
    window.addEventListener('pagehide', release);
    const poll = async () => {
      if (disposed) return;
      try {
        const next = await api(`/browser/sessions/${id.current}`);
        if (disposed) return;
        setState(next);
        if (next.url) setAddress(previous => document.activeElement?.id === 'browser-address' ? previous : next.url);
        if (next.has_frame && next.frame_version !== version.current) {
          version.current = next.frame_version;
          setFrame(`/api/browser/sessions/${id.current}/frame?v=${next.frame_version}`);
        }
        const currentSignature = JSON.stringify(next.items);
        if (currentSignature !== signature.current) {
          signature.current = currentSignature;
          notify.current(next.items || [], id.current);
        }
        if (next.status === 'error' || next.status === 'closed') return;
        timer = setTimeout(poll, 850);
      } catch (err) {
        if (!disposed) { setError(err.message); timer = setTimeout(poll, 3000); }
      }
    };
    api('/browser/sessions', { url }).then(session => {
      id.current = session.session_id;
      if (disposed) { release(); return; }
      setState(session);
      poll();
    }).catch(err => { if (!disposed) { setError(err.message); setState(previous => ({ ...previous, status: 'error' })); } });
    return () => {
      disposed = true;
      clearTimeout(timer);
      window.removeEventListener('pagehide', release);
      release();
      document.body.style.overflow = previousOverflow;
    };
  }, [url]);

  const command = payload => {
    commandQueue.current = commandQueue.current.then(async () => {
      if (!id.current || closing.current) return;
      try { await api(`/browser/sessions/${id.current}/command`, payload); setError(''); }
      catch (err) { setError(err.message); }
    });
    return commandQueue.current;
  };
  const close = () => { closing.current = true; onClose(); };
  const click = event => {
    const box = event.currentTarget.getBoundingClientRect();
    preview.current.focus();
    command({ action: 'click', x: Math.min(959, Math.max(0, (event.clientX - box.left) * 960 / box.width)), y: Math.min(539, Math.max(0, (event.clientY - box.top) * 540 / box.height)) });
  };
  const key = event => {
    if (event.key === 'Escape') return;
    const control = event.ctrlKey || event.metaKey;
    if (control && event.key.toLowerCase() === 'v') return; // paste handled below
    let remoteKey = event.key;
    if (control && remoteKey.toLowerCase() === 'a') remoteKey = 'ControlOrMeta+A';
    else if (control || event.altKey) return;
    else if (remoteKey === 'Tab') return; // Keep Tab for moving between app controls.
    else if (remoteKey === ' ') remoteKey = 'Space';
    event.preventDefault();
    if (event.key.length === 1 && !control && event.key !== ' ') command({ action: 'type', text: event.key });
    else if (['Enter', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown', 'Space', 'ControlOrMeta+A'].includes(remoteKey)) command({ action: 'key', key: remoteKey });
  };
  const live = state.status === 'ready';
  const detected = (state.items || []).map(item => ({ ...item, ...items.find(x => x.id === item.id && x.browser_session_id === id.current), browser_session_id: id.current }));
  return <dialog ref={dialog} className="advanced-dialog" aria-labelledby="browser-heading" onCancel={event => { event.preventDefault(); close(); }}>
    <div className="browser-heading"><div><h2 id="browser-heading">Advanced browser</h2><p>Play the video here. New tabs and page changes wait for your permission.</p></div><button className="theme-button" onClick={close} aria-label="Close browser viewer"><Icon name="close"/></button></div>
    {state.tabs?.length > 0 && <div className="browser-tabs" role="group" aria-label="Browser tabs">{state.tabs.map(tab => <button key={tab.id} className={tab.id === state.active_tab ? 'active-tab' : ''} onClick={() => command({ action: 'activate', tab_id: tab.id })} title={tab.url}>{tab.title || 'Video page'}</button>)}</div>}
    <form className="browser-toolbar" onSubmit={event => { event.preventDefault(); command({ action: 'navigate', url: address }); }}>
      <button className="browser-tool" type="button" disabled={!live} aria-label="Go back" onClick={() => command({ action: 'back' })}><Icon name="arrow" className="back-arrow" size={18}/></button>
      <button className="browser-tool" type="button" disabled={!live} aria-label="Reload page" onClick={() => command({ action: 'reload' })}><Icon name="refresh" size={17}/></button>
      <label className="sr-only" htmlFor="browser-address">Browser page address</label><input id="browser-address" type="url" required value={address} onInput={event => setAddress(event.target.value)} disabled={!live}/>
      <button className="button secondary" type="submit" disabled={!live}>Go</button>
    </form>
    <div className="browser-viewport">
      {frame ? <img ref={preview} src={frame} alt="Interactive page preview. Click a player or close an overlay; type while the preview is focused." draggable={false} tabIndex={0} onClick={click} onKeyDown={key} onPaste={event => { event.preventDefault(); command({ action: 'type', text: event.clipboardData.getData('text').slice(0, 2000) }); }}/>
        : <div className="browser-placeholder">{state.status === 'starting' || live ? <><span className="spinner"/><strong>Opening the page…</strong><p>The browser can take a few seconds to start.</p></> : <><Icon name="play" size={32}/><strong>Browser preview unavailable</strong><p>Install the optional browser extra and Chromium, then try again.</p><code>python -m pip install -e '.[browser]'<br/>python -m playwright install chromium</code></>}</div>}
    </div>
    <div className="browser-popups" aria-live="polite">{state.navigations?.map(intent => <div className="popup-decision" key={intent.id}><div><strong>{intent.kind === 'popup' ? 'Open a new tab?' : 'Leave this page?'}</strong><p>This page wants to open {intent.hostname}. Stay here or continue?</p><p title={intent.url}>{intent.url}</p></div><div className="popup-actions"><button className="button secondary" onClick={() => command({ action: 'dismiss_navigation', navigation_id: intent.id })}>Stay here</button><button className="button primary" onClick={() => command({ action: 'follow_navigation', navigation_id: intent.id })}>{intent.kind === 'popup' ? 'Go to new tab' : 'Continue'}<Icon name="arrow" size={16}/></button></div></div>)}{state.popups?.map(tab => <div className="popup-decision" key={tab.id}><div><strong>This page wants to open a new tab</strong><p title={tab.url}>{tab.url === 'about:blank' ? 'Waiting for the new tab’s address…' : tab.url}</p></div><div className="popup-actions"><button className="button secondary" onClick={() => command({ action: 'stay', tab_id: tab.id })}>Stay here</button><button className="button primary" disabled={!tab.url?.startsWith('http')} onClick={() => command({ action: 'activate', tab_id: tab.id })}>Go to new tab<Icon name="arrow" size={16}/></button></div></div>)}</div>
    <div className="browser-controls"><p>Click the preview to interact. It refreshes periodically and has no audio.</p><div><button className="browser-tool" disabled={!live} onClick={() => command({ action: 'key', key: 'Tab' })}>Focus next field</button><button className="browser-tool" disabled={!live} onClick={() => command({ action: 'scroll', delta: -450 })}>Scroll up</button><button className="browser-tool" disabled={!live} onClick={() => command({ action: 'scroll', delta: 450 })}>Scroll down</button>{state.tabs?.length > 1 && <button className="browser-tool" onClick={() => command({ action: 'close_tab', tab_id: state.active_tab })}>Close this tab</button>}</div></div>
    {(error || state.error) && <p className="notice error-notice" role="alert">{error || state.error}</p>}
    <section className="browser-media" aria-labelledby="browser-media-heading"><div className="section-heading"><h3 id="browser-media-heading">Detected media{detected.length > 0 ? ` · ${detected.length}` : ''}</h3><span className="browser-scan-status">{live ? <><span/>Scanning as you browse</> : state.status === 'starting' ? 'Waiting for browser' : 'Browser stopped'}</span></div>
      {detected.length ? <div className="media-grid">{detected.map((item, index) => <MediaCard key={item.id} item={item} index={index} job={jobs[item.jobId]} busy={busy[item.id]} onDownload={onDownload} onCancel={onCancel}/>)}</div> : <p className="browser-empty">No media detected yet. Close an overlay or press Play in the preview to load the video. Ads may also appear in detected media; choose the video you want.</p>}
    </section>
    <Toast toast={toast} dismiss={dismissToast}/>
  </dialog>;
}
