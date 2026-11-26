import { ToastProvider } from "./components/Toast";
import { LEAD_READERS, POSTSALES_ROLES } from "./lib/types";
import { Suspense, lazy } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import axios from "axios";
import { AppLayout } from "./components/AppLayout";
import { RequireAuth, RequireRole } from "./components/RouteGuards";
import { Spinner } from "./components/ui";
import { AuthProvider } from "./hooks/useAuth";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { EditLeadPage, NewLeadPage } from "./pages/leads/LeadFormPage";
import { NotFoundPage } from "./pages/NotFoundPage";

// Pages load on first visit, so phones download less up front.
const AccountPage = lazy(() => import("./pages/AccountPage").then((m) => ({ default: m.AccountPage })));
const CallsPage = lazy(() => import("./pages/CallsPage").then((m) => ({ default: m.CallsPage })));
const ChannelPartnersPage = lazy(() => import("./pages/ChannelPartnersPage").then((m) => ({ default: m.ChannelPartnersPage })));
const ChannelPartnerDetailPage = lazy(() => import("./pages/ChannelPartnersPage").then((m) => ({ default: m.ChannelPartnerDetailPage })));
const DemandLetterPage = lazy(() => import("./pages/postsales/DemandLetterPage").then((m) => ({ default: m.DemandLetterPage })));
const AgreementDraftPage = lazy(() => import("./pages/postsales/AgreementDraftPage").then((m) => ({ default: m.AgreementDraftPage })));
const ServicePage = lazy(() => import("./pages/service/ServicePage").then((m) => ({ default: m.ServicePage })));
const ServiceSettingsPage = lazy(() => import("./pages/service/ServiceSettingsPage").then((m) => ({ default: m.ServiceSettingsPage })));
const ServiceReportsPage = lazy(() => import("./pages/service/ServiceReportsPage").then((m) => ({ default: m.ServiceReportsPage })));
const TicketPage = lazy(() => import("./pages/service/TicketPage").then((m) => ({ default: m.TicketPage })));
const CommunicationsPage = lazy(() => import("./pages/comms/CommunicationsPage").then((m) => ({ default: m.CommunicationsPage })));
const PortalApp = lazy(() => import("./portal/PortalApp").then((m) => ({ default: m.PortalApp })));
const MisPage = lazy(() => import("./pages/mis/MisPage").then((m) => ({ default: m.MisPage })));
const CalendarPage = lazy(() => import("./pages/calendar/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const InspectionReportPage = lazy(() => import("./pages/postsales/InspectionReportPage").then((m) => ({ default: m.InspectionReportPage })));
const CancellationLetterPage = lazy(() => import("./pages/postsales/CancellationLetterPage").then((m) => ({ default: m.CancellationLetterPage })));
const StatementPage = lazy(() => import("./pages/postsales/StatementPage").then((m) => ({ default: m.StatementPage })));
const CostSheetPage = lazy(() => import("./pages/CostSheetPage").then((m) => ({ default: m.CostSheetPage })));
const PostSalesPage = lazy(() => import("./pages/postsales/PostSalesPage").then((m) => ({ default: m.PostSalesPage })));
const CasePage = lazy(() => import("./pages/postsales/CasePage").then((m) => ({ default: m.CasePage })));
const BookingsPage = lazy(() => import("./pages/BookingsPage").then((m) => ({ default: m.BookingsPage })));
const BookingDetailPage = lazy(() => import("./pages/BookingDetailPage").then((m) => ({ default: m.BookingDetailPage })));
const InboxPage = lazy(() => import("./pages/InboxPage").then((m) => ({ default: m.InboxPage })));
const ConnectionsPage = lazy(() => import("./pages/ConnectionsPage").then((m) => ({ default: m.ConnectionsPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const MarketingPage = lazy(() => import("./pages/MarketingPage").then((m) => ({ default: m.MarketingPage })));
const PipelinePage = lazy(() => import("./pages/PipelinePage").then((m) => ({ default: m.PipelinePage })));
const FollowUpsPage = lazy(() => import("./pages/FollowUpsPage").then((m) => ({ default: m.FollowUpsPage })));
const LeadDetailPage = lazy(() => import("./pages/leads/LeadDetailPage").then((m) => ({ default: m.LeadDetailPage })));
const LeadsPage = lazy(() => import("./pages/leads/LeadsPage").then((m) => ({ default: m.LeadsPage })));
const ProjectDetailPage = lazy(() => import("./pages/projects/ProjectDetailPage").then((m) => ({ default: m.ProjectDetailPage })));
const ProjectsPage = lazy(() => import("./pages/projects/ProjectsPage").then((m) => ({ default: m.ProjectsPage })));
const VisitsPage = lazy(() => import("./pages/VisitsPage").then((m) => ({ default: m.VisitsPage })));
const UsersPage = lazy(() => import("./pages/users/UsersPage").then((m) => ({ default: m.UsersPage })));

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // Retry network blips once, but never auth/permission/not-found errors.
        retry: (count, err) =>
          count < 1 && !(axios.isAxiosError(err) && [401, 403, 404].includes(err.response?.status ?? 0)),
      },
    },
  });
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        {/* Printable page: no menu around it */}
        <Route path="cost-sheet/:unitId" element={<CostSheetPage />} />
        <Route path="statement/:caseId" element={<StatementPage />} />
        <Route path="cancellation-letter/:caseId" element={<CancellationLetterPage />} />
        <Route path="inspection-report/:caseId/:inspectionId" element={<InspectionReportPage />} />
        <Route path="agreement-draft/:caseId" element={<AgreementDraftPage />} />
        <Route path="demand-letter/:caseId/:demandId" element={<DemandLetterPage />} />
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route element={<RequireRole roles={POSTSALES_ROLES} />}>
            <Route path="post-sales" element={<PostSalesPage />} />
            <Route path="calendar" element={<CalendarPage />} />
            <Route path="mis" element={<MisPage />} />
            <Route path="communications" element={<CommunicationsPage />} />
            <Route path="service" element={<ServicePage />} />
            <Route path="service/settings" element={<ServiceSettingsPage />} />
            <Route path="service/reports" element={<ServiceReportsPage />} />
            <Route path="service/:ticketId" element={<TicketPage />} />
            <Route path="post-sales/:caseId" element={<CasePage />} />
          </Route>
          <Route path="bookings" element={<BookingsPage />} />
          <Route path="bookings/:bookingId" element={<BookingDetailPage />} />
          <Route element={<RequireRole roles={LEAD_READERS} />}>
            <Route path="leads" element={<LeadsPage />} />
            <Route path="leads/:id" element={<LeadDetailPage />} />
          </Route>
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route element={<RequireRole roles={["admin", "manager", "executive"]} />}>
            <Route path="follow-ups" element={<FollowUpsPage />} />
            <Route path="pipeline" element={<PipelinePage />} />
            <Route path="channel-partners" element={<ChannelPartnersPage />} />
            <Route path="channel-partners/:partnerId" element={<ChannelPartnerDetailPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="visits" element={<VisitsPage />} />
            <Route path="calls" element={<CallsPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin", "manager", "executive"]} />}>
            <Route path="leads/new" element={<NewLeadPage />} />
            <Route path="leads/:id/edit" element={<EditLeadPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin", "manager"]} />}>
            <Route path="marketing" element={<MarketingPage />} />
            <Route path="inbox" element={<InboxPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin"]} />}>
            <Route path="users" element={<UsersPage />} />
            <Route path="connections" element={<ConnectionsPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
    </Suspense>
  );
}

const queryClient = createQueryClient();

export default function App() {
  // The customer portal is a separate app: no staff sign-in, menus or data
  if (window.location.pathname.startsWith("/portal")) return <Suspense fallback={<p style={{ padding: 32 }}>Loading…</p>}><PortalApp /></Suspense>;
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
