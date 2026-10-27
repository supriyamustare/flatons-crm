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
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="leads" element={<LeadsPage />} />
          <Route path="leads/:id" element={<LeadDetailPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route element={<RequireRole roles={["admin", "manager", "executive"]} />}>
            <Route path="follow-ups" element={<FollowUpsPage />} />
            <Route path="pipeline" element={<PipelinePage />} />
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
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
