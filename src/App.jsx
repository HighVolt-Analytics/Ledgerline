import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import QuantumLedgerLinkPage from './pages/QuantumLedgerLinkPage';
import InteractiveTourPage from './pages/InteractiveTourPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<QuantumLedgerLinkPage />} />
        <Route path="/interactive-tour" element={<InteractiveTourPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
