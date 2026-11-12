export default function ToastNotification({ toasts }) {
  return <div className="toasts">{toasts.map((toast) => <div key={toast.id} className={`toast ${toast.type}`}>{toast.message}</div>)}</div>;
}
