import Header from '../components/layout/Header';
import Footer from '../components/layout/Footer';
import SectionDivider from '../components/layout/SectionDivider';
import HeroSection from '../components/sections/HeroSection';
import StatsSection from '../components/sections/StatsSection';
import HowItWorksSection from '../components/sections/HowItWorksSection';
import ControlsSection from '../components/sections/ControlsSection';
import CaptureSection from '../components/sections/CaptureSection';
import ProcurementSection from '../components/sections/ProcurementSection';
import RuleBookSection from '../components/sections/RuleBookSection';
import PaymentsSection from '../components/sections/PaymentsSection';
import MultiEntitySection from '../components/sections/MultiEntitySection';
import IntegrationsSection from '../components/sections/IntegrationsSection';
import PromiseSection from '../components/sections/PromiseSection';
import PricingSection from '../components/sections/PricingSection';
import FaqSection from '../components/sections/FaqSection';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main>
        <HeroSection />
        <SectionDivider />
        <StatsSection />
        <SectionDivider />
        <HowItWorksSection />
        <SectionDivider />
        <ControlsSection />
        <SectionDivider />
        <CaptureSection />
        <SectionDivider />
        <ProcurementSection />
        <SectionDivider />
        <RuleBookSection />
        <SectionDivider />
        <PaymentsSection />
        <SectionDivider />
        <MultiEntitySection />
        <SectionDivider />
        <IntegrationsSection />
        <PromiseSection />
        <PricingSection />
        <SectionDivider />
        <FaqSection />
        <Footer />
      </main>
    </div>
  );
}
