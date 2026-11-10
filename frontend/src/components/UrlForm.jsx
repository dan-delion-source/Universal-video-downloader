import { useState } from 'preact/hooks';
import Icon from './Icon';
export default function UrlForm({ onScan, scanning, disabled, advanced, onAdvanced }) {
  const [url, setUrl] = useState('');
  return <form onSubmit={e => { e.preventDefault(); onScan(url.trim()); }} className="url-form">
    <label htmlFor="page-url">Page or video URL</label>
    <div className="input-shell"><Icon name="link" size={23}/><input id="page-url" type="url" required placeholder="https://example.com/watch/video" value={url} onInput={e => setUrl(e.target.value)} autoComplete="off" spellCheck={false} disabled={scanning || disabled}/>
      <button className="button primary" disabled={scanning || disabled} type="submit">{scanning ? <><span className="spinner"/>Scanning…</> : <>{advanced ? 'View' : 'Find videos'}<Icon name="arrow" size={18}/></>}</button>
    </div>
    <label className="advanced-toggle"><input type="checkbox" checked={advanced} onChange={event => onAdvanced(event.target.checked)} disabled={scanning || disabled}/><span>Advanced mode</span><small>Browse the page and detect media as it plays</small></label>
    <div className="input-caption"><span>Paste a webpage, video, or playlist link.</span><span><kbd>enter</kbd> to scan</span></div>
  </form>;
}
