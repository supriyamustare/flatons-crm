import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import axios from "axios";
import { AppLayout } from "./components/AppLayout";
import { RequireAuth, RequireRole } from "./components/RouteGuards";
import { AuthProvider } from "./hooks/useAuth";
import { AccountPage } from "./pages/AccountPage";
import { CallsPage } from "./pages/CallsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FollowUpsPage } from "./pages/FollowUpsPage";
import { LoginPage } from "./pages/LoginPage";
import { LeadDetailPage } from "./pages/leads/LeadDetailPage";
import { EditLeadPage, NewLeadPage } from "./pages/leads/LeadFormPage";
import { LeadsPage } from "./pages/leads/LeadsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { VisitsPage } from "./pages/VisitsPage";
import { UsersPage } from "./pages/users/UsersPage";

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
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="leads" element={<LeadsPage />} />
          <Route path="leads/:id" element={<LeadDetailPage />} />
          <Route element={<RequireRole roles={["admin", "manager", "executive"]} />}>
            <Route path="follow-ups" element={<FollowUpsPage />} />
            <Route path="visits" element={<VisitsPage />} />
            <Route path="calls" element={<CallsPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin", "manager", "executive"]} />}>
            <Route path="leads/new" element={<NewLeadPage />} />
            <Route path="leads/:id/edit" element={<EditLeadPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin"]} />}>
            <Route path="users" element={<UsersPage />} />
            <Route path="projects" element={<ProjectsPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
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
