import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppRoutes, createQueryClient } from "../App";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "../hooks/useAuth";
import { ToastProvider } from "../components/Toast";

/** Render the whole app at a given URL, with a fresh cache. */
export function renderApp(path = "/") {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

/** Render one component with the app's providers, once the signed-in user has loaded. */
export function renderWithProviders(ui: ReactNode) {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  function WhenSignedIn({ children }: { children: ReactNode }) {
    const auth = useAuth();
    return auth.user ? <>{children}</> : null;
  }
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter><WhenSignedIn>{ui}</WhenSignedIn></MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}
