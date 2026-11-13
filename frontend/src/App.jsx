import Layout from "./components/Layout.jsx";
import { ErrorMessage, Loading } from "./components/ui.jsx";
import { useAsync } from "./hooks/useAsync.js";
import { useRoute } from "./hooks/useRoute.js";
import { useChartColors, useTheme } from "./hooks/useTheme.js";
import { api, getAccessKey } from "./services/api.js";
import AnalysisResults from "./pages/AnalysisResults.jsx";
import AnomalyExplorer from "./pages/AnomalyExplorer.jsx";
import DatasetProfile from "./pages/DatasetProfile.jsx";
import Datasets from "./pages/Datasets.jsx";
import LiveMonitoring from "./pages/LiveMonitoring.jsx";
import NotFound from "./pages/NotFound.jsx";
import Overview from "./pages/Overview.jsx";
import Reports from "./pages/Reports.jsx";
import Settings from "./pages/Settings.jsx";
import Upload from "./pages/Upload.jsx";

function Page({ route, info, colors }) {
  const [first, id, sub] = route.parts;
  if (!first) return <Overview />;
  if (first === "upload") return <Upload info={info} />;
  if (first === "datasets" && !id) return <Datasets />;
  if (first === "datasets" && /^\d+$/.test(id)) {
    if (sub === "profile") return <DatasetProfile id={Number(id)} colors={colors} />;
    if (sub === "results") return <AnalysisResults id={Number(id)} colors={colors} />;
    if (sub === "anomalies") return <AnomalyExplorer id={Number(id)} />;
  }
  if (first === "reports") return <Reports />;
  if (first === "monitoring") return <LiveMonitoring colors={colors} info={info} />;
  if (first === "settings") return <Settings info={info} />;
  return <NotFound />;
}

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const colors = useChartColors(theme);
  const info = useAsync(() => api.info(), []);
  return (
    <Layout route={route} theme={theme} onToggleTheme={toggle}>
      {info.loading && <Loading label="Connecting to the backend" />}
      {info.error && <ErrorMessage error={info.error} onRetry={info.reload} />}
      {info.data && (
        <>
          {info.data.access_key_required && !getAccessKey() && route.parts[0] !== "settings" && (
            <div className="alert warning" style={{ marginBottom: "1rem" }}>
              This server requires an access key. <a href="#/settings">Enter it in Settings</a>.
            </div>
          )}
          <Page key={route.path} route={route} info={info.data} colors={colors} />
        </>
      )}
    </Layout>
  );
}
