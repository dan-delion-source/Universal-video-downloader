import { fileSize } from '../api';
export default function ProgressBar({ job }) {
  const label = { queued: 'Waiting in queue', downloading: 'Downloading', merging: 'Preparing your file', complete: 'Ready to save', cancelled: 'Cancelled', error: 'Download failed' }[job.status];
  return <div className="progress-block" aria-live="polite"><div className="progress-label"><span>{label}</span><span>{job.status === 'downloading' ? `${Math.round(job.percent)}%` : ''}</span></div>
    <div className={`progress-track ${['merging', 'queued'].includes(job.status) ? 'indeterminate' : ''}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.percent)}><span style={{ transform: `scaleX(${(job.percent || 0) / 100})` }}/></div>
    {job.speed > 0 && <small>{fileSize(job.speed)}/s{job.eta != null ? ` · ${Math.ceil(job.eta)}s remaining` : ''}</small>}
    {job.error && <p className="inline-error">{job.error}</p>}
  </div>;
}
