import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import CharacterListPage from "./pages/CharacterListPage";
import CharacterEditPage from "./pages/CharacterEditPage";
import EconomyManagerPage from "./pages/EconomyManagerPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<CharacterListPage />} />
      <Route path="/economy-manager/*" element={<EconomyManagerPage />} />
      <Route path="/edit/:id" element={<CharacterEditPage />} />
      <Route path="/:characterSlug" element={<CharacterEditPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
