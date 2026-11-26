import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import { Toaster } from "sonner";
import { ApiError } from "./api/client";
import "./index.css";
import { router } from "./router";

function onAuthError(error: unknown) {
  if (error instanceof ApiError && error.status === 401 && !window.location.pathname.startsWith("/signin")) {
    queryClient.clear();
    router.navigate("/signin");
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onAuthError }),
  mutationCache: new MutationCache({ onError: onAuthError }),
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => error instanceof ApiError && (error.status === 0 || error.status >= 500) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="top-center" richColors closeButton toastOptions={{ style: { fontFamily: "inherit" } }} />
    </QueryClientProvider>
  </StrictMode>,
);
