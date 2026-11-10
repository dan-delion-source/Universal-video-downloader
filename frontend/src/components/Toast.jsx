import Icon from './Icon';
export default function Toast({ toast, dismiss }) {
  return toast && <div className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}><span>{toast.message}</span><button onClick={dismiss} aria-label="Dismiss notification"><Icon name="close" size={18}/></button></div>;
}
