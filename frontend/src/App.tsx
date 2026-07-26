import { Navigate, Route, Routes } from "react-router-dom";

import AnnotationPage from "./pages/AnnotationPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import DatasetListPage from "./pages/DatasetListPage";
import JobCenter from "./components/JobCenter";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<DatasetListPage />} />
        <Route path="/datasets/:datasetId" element={<DatasetDetailPage />} />
        <Route path="/datasets/:datasetId/annotate" element={<AnnotationPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <JobCenter />
    </>
  );
}
