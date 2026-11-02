import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LogsView } from "../ui/LogsView";
import { Compose } from "../screens/Compose";
import { Detect } from "../screens/Detect";
import { Edit } from "../screens/Edit";
import { Home } from "../screens/Home";
import { Render } from "../screens/Render";
import { Review } from "../screens/Review";
import { Select } from "../screens/Select";
import { Upload } from "../screens/Upload";
import { Shell } from "./Shell";

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Home />} />
          <Route path="upload" element={<Upload />} />
          <Route path="logs" element={<LogsView />} />
          <Route path="jobs/:taskId/detect" element={<Detect />} />
          <Route path="jobs/:taskId/select" element={<Select />} />
          <Route path="jobs/:taskId/compose" element={<Compose />} />
          <Route path="jobs/:taskId/edit" element={<Edit />} />
          <Route path="jobs/:taskId/review" element={<Review />} />
          <Route path="jobs/:taskId/render" element={<Render />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
