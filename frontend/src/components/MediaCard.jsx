import { useState } from 'preact/hooks';
import Icon from './Icon';
import ProgressBar from './ProgressBar';
import { fileUrl, fileSize } from '../api';
const duration = seconds => { const m = Math.floor(seconds / 60); return `${m}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`; };
export default function MediaCard({ item, index, job, onDownload, onCancel, busy, onView }) {
  const [quality, setQuality] = useState('best');
  const active = job && ['queued', 'downloading', 'merging'].includes(job.status);
  const selected = item.formats.find(f => f.format_id === quality) || item.formats[0];
  return <article className="media-card">
    <div className="media-preview">
      {item.thumbnail ? <img src={`/api/thumbnails/${item.id}`} alt="" loading="lazy" onError={e => { e.currentTarget.style.display = 'none'; }}/> : null}
      <div className="preview-mark"><Icon name={item.drm ? 'lock' : 'play'} size={42}/></div>
      <span className="media-index">VIDEO {String(index + 1).padStart(2, '0')}</span>
      {item.duration > 0 && <span className="duration">{duration(item.duration)}</span>}
    </div>
    <div className="media-details"><span className="source-label">{item.source === 'yt-dlp' ? 'Site extractor' : item.source === 'sniff' ? 'Browser scan' : 'Page scan'}<span>{item.drm ? 'Protected' : selected?.ext?.toUpperCase()}</span></span>
      <h3>{item.title}</h3>
      {onView && <button className="text-button view-page-button" onClick={onView}><Icon name="play" size={15}/>View page</button>}
      {item.drm ? <p className="protected"><Icon name="lock" size={17}/>This video is DRM-protected and can’t be downloaded.</p> : <>
        <label className="quality-label" htmlFor={`quality-${item.id}`}>Download quality</label>
        <select id={`quality-${item.id}`} value={quality} onChange={e => setQuality(e.target.value)} disabled={active || busy}>
          <option value="best">Best available · automatic</option>
          {item.formats.filter(f => f.format_id !== 'best').map(f => <option value={f.format_id} key={f.format_id}>{f.resolution}{f.fps ? ` · ${f.fps} fps` : ''} · {f.ext.toUpperCase()}{f.filesize ? ` · ${fileSize(f.filesize)}` : ''}{f.note ? ` · ${f.note}` : ''}</option>)}
        </select>
        {job && <ProgressBar job={job}/>}
        {job?.status === 'complete' ? <a className="button primary full" href={fileUrl(job.filename)} download><Icon name="download" size={17}/>Save file</a> : active ? <button className="button secondary full" onClick={() => onCancel(job.id)}><Icon name="close" size={17}/>Cancel download</button> : <button className="button secondary full" disabled={busy} onClick={() => onDownload(item, quality)}><Icon name="download" size={17}/>{busy ? 'Starting…' : job ? 'Download again' : 'Download video'}</button>}
      </>}
    </div>
  </article>;
}
