import { Navigate, Route, Routes } from "react-router-dom";

import DatasetDetailPage from "./pages/DatasetDetailPage";
import DatasetListPage from "./pages/DatasetListPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DatasetListPage />} />
      <Route path="/datasets/:datasetId" element={<DatasetDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
