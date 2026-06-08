import { ThemeProvider } from './context/ThemeContext';
import LandingPage from './pages/LandingPage';

export default function App() {
  return (
    <ThemeProvider>
      <LandingPage />
    </ThemeProvider>
  );
}
