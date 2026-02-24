import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import PageEditor from "./pages/PageEditor";
import PageList from "./pages/PageList";
import PageReader from "./pages/PageReader";
import NewPage from "./pages/NewPage";
import WikiAdmin from "./pages/WikiAdmin";

function App() {
  return (
    <div className="wiki-shell">
      <div className="wiki-content">
        <Routes>
          <Route path="/" element={<PageList />} />
          <Route path="/new" element={<NewPage />} />
          <Route path="/admin" element={<WikiAdmin />} />
          <Route path="/slug/:slug" element={<PageReader />} />
          <Route path="/:id/edit" element={<PageEditor />} />
          <Route path="/:id" element={<PageReader />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default App;
