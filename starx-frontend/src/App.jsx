import { useState } from "react";
import AuthScreen from "./components/AuthScreen";
import KnowledgeBaseModal from "./components/KnowledgeBaseModal";
import Layout from "./components/Layout";
import SplashScreen from "./components/SplashScreen";
import { useStarxApp } from "./hooks/useStarxApp";
import { useTheme } from "./hooks/useTheme";
import AccountProfile from "./pages/AccountProfile";
import AccountReport from "./pages/AccountReport";
import CompetitorMonitor from "./pages/CompetitorMonitor";
import HotspotBoards from "./pages/HotspotBoards";
import ContentCreation from "./pages/ContentCreation";
import DataDashboard from "./pages/DataDashboard";
import MaterialLibrary from "./pages/MaterialLibrary";
import ProcessManagement from "./pages/ProcessManagement";
import Toolbox from "./pages/Toolbox";
import TopicCenter from "./pages/TopicCenter";

const pageMap = {
  topic: TopicCenter,
  creation: ContentCreation,
  process: ProcessManagement,
  material: MaterialLibrary,
  dashboard: DataDashboard,
  account: AccountProfile,
  report: AccountReport,
  competitor: CompetitorMonitor,
  hotspot: HotspotBoards,
  toolbox: Toolbox,
};

export default function App() {
  const app = useStarxApp();
  const { theme, setTheme } = useTheme();
  const [splash, setSplash] = useState(true);
  const Page = pageMap[app.activePage] || TopicCenter;

  if (splash) {
    return <SplashScreen onDone={() => setSplash(false)} />;
  }

  if (!app.currentUser) {
    return <AuthScreen app={app} theme={theme} setTheme={setTheme} />;
  }

  return (
    <>
      <Layout app={app} theme={theme} setTheme={setTheme}>
        <Page app={app} />
      </Layout>
      <KnowledgeBaseModal app={app} />
    </>
  );
}
