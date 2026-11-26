import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell, RequireAuth } from "@/components/AppShell";
import { AuthProvider } from "@/lib/auth";
import { LoginPage } from "@/pages/LoginPage";
import { AdminPage } from "@/pages/AdminPage";
import { NotFound } from "@/pages/Placeholder";
import { ResultsPage } from "@/pages/ResultsPage";
import { StudyPage } from "@/pages/StudyPage";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: (n, e) => n < 1 && !("status" in e && (e as { status: number }).status < 500) } },
});

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <StudyPage /> },
          { path: "ket-qua", element: <ResultsPage /> },
          { element: <RequireAuth admin />, children: [{ path: "quan-tri", element: <AdminPage /> }] },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
