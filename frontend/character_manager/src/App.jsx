import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import CharacterListPage from "./pages/CharacterListPage";
import CharacterEditPage from "./pages/CharacterEditPage";
import EconomyManagerPage from "./pages/EconomyManagerPage";
import ItemManagerPage from "./pages/ItemManagerPage";

function App() {
  const isEconomyApp = window.location.pathname.startsWith("/economy-manager");
  const isItemManagerApp = window.location.pathname.startsWith("/item-manager");
  if (isEconomyApp) {
    return (
      <Routes>
        <Route path="/*" element={<EconomyManagerPage />} />
      </Routes>
    );
  }
  if (isItemManagerApp) {
    return (
      <Routes>
        <Route path="/*" element={<ItemManagerPage />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<CharacterListPage />} />
      <Route path="/edit/:id" element={<CharacterEditPage />} />
      <Route path="/:characterSlug" element={<CharacterEditPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
