export async function api(path, body, signal) {
  let response;
  try {
    response = await fetch(`/api${path}`, body === undefined ? { signal } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the local server. Check that python run.py is still running.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Please try again.');
  return data;
}
export function watchJob(id, onEvent, onError) {
  const source = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
  source.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    onEvent(event);
    if (['complete', 'cancelled', 'error'].includes(event.status)) source.close();
  };
  source.onerror = () => { if (source.readyState === EventSource.CLOSED) onError?.(); };
  return () => source.close();
}
export const fileUrl = name => `/api/files/${encodeURIComponent(name)}`;
export const fileSize = bytes => !bytes ? '' : bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
