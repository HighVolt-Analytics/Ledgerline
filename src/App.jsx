import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import QuantumLedgerLinkPage from './pages/QuantumLedgerLinkPage';
import InteractiveTourPage from './pages/InteractiveTourPage';
import ResourcesPage from './pages/ResourcesPage';
import SpectraCaseStudyPage from './pages/SpectraCaseStudyPage';
import PactifyCaseStudyPage from './pages/PactifyCaseStudyPage';
import BookDemoPage from './pages/BookDemoPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<QuantumLedgerLinkPage />} />
        <Route path="/interactive-tour" element={<InteractiveTourPage />} />
        <Route path="/resources" element={<ResourcesPage />} />
        <Route path="/book-demo" element={<BookDemoPage />} />
        <Route path="/industries/spectra" element={<SpectraCaseStudyPage />} />
        <Route path="/industries/pactify" element={<PactifyCaseStudyPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
