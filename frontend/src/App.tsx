import { Navigate, Route, Routes } from "react-router-dom";

import AnnotationPage from "./pages/AnnotationPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import DatasetListPage from "./pages/DatasetListPage";
import DatasetLibraryPage from "./pages/DatasetLibraryPage";
import LocalBrowsePage from "./pages/LocalBrowsePage";
import ValidationResultPage from "./pages/ValidationResultPage";
import ValidationPage from "./pages/ValidationPage";
import TriagePage from "./pages/TriagePage";
import StartupGuard from "./components/StartupGuard";
import JobCenter from "./components/JobCenter";
import PortableControls from "./components/PortableControls";

export default function App() {
  return (
    <StartupGuard>
      <Routes>
        <Route path="/" element={<DatasetListPage />} />
        <Route path="/library" element={<DatasetLibraryPage />} />
        <Route path="/browse" element={<LocalBrowsePage />} />
        <Route path="/datasets/:datasetId" element={<DatasetDetailPage />} />
        <Route path="/datasets/:datasetId/annotate" element={<AnnotationPage />} />
        <Route path="/datasets/:datasetId/validate" element={<ValidationPage />} />
        <Route path="/datasets/:datasetId/validate/:runId" element={<ValidationResultPage />} />
        <Route path="/datasets/:datasetId/triage" element={<TriagePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <JobCenter />
      <PortableControls />
    </StartupGuard>
  );
}
