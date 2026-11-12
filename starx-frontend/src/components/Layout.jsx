import AddAccountModal from "./AddAccountModal";
import Sidebar from "./Sidebar";
import StarfieldCanvas from "./StarfieldCanvas";
import TopBar from "./TopBar";
import ToastNotification from "./ToastNotification";

export default function Layout({ app, children, theme, setTheme }) {
  return (
    <div className="shell">
      <StarfieldCanvas />
      <TopBar app={app} theme={theme} setTheme={setTheme} />
      <div className="body">
        <Sidebar
          activePage={app.activePage}
          setActivePage={app.setActivePage}
          onOpenCreation={app.startBlankCreation}
        />
        <main className="main">
          <div className="page-transition" key={app.activePage}>
            {children}
          </div>
        </main>
      </div>
      <AddAccountModal app={app} />
      <ToastNotification toasts={app.toasts} />
    </div>
  );
}
