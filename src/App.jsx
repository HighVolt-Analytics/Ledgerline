import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import QuantumLedgerLinkPage from './pages/QuantumLedgerLinkPage';
import InteractiveTourPage from './pages/InteractiveTourPage';
import ResourcesPage from './pages/ResourcesPage';
import SpectraCaseStudyPage from './pages/SpectraCaseStudyPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<QuantumLedgerLinkPage />} />
        <Route path="/interactive-tour" element={<InteractiveTourPage />} />
        <Route path="/resources" element={<ResourcesPage />} />
        <Route path="/industries/spectra" element={<SpectraCaseStudyPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
