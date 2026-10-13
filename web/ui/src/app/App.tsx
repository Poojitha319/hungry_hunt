import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Route, Routes } from "react-router";
import { CompaniesPage } from "../features/companies/CompaniesPage";
import { CoveragePage } from "../features/coverage/CoveragePage";
import { DigestPage } from "../features/digest/DigestPage";
import { JobPage } from "../features/job/JobPage";
import { ApiProvider } from "../shared/api/context";
import { getToken } from "../shared/auth/token";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 60_000 } } });

function Layout() {
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "font-semibold text-gray-900" : "text-gray-600");
  return (
    <div className="mx-auto max-w-3xl p-4">
      <nav className="mb-4 flex items-center gap-4 border-b border-gray-200 pb-2 text-sm">
        <span className="text-base font-bold">Hungry Hunt</span>
        <NavLink to="/" end className={link}>Digest</NavLink>
        <NavLink to="/companies" className={link}>Companies</NavLink>
        <NavLink to="/coverage" className={link}>Coverage</NavLink>
      </nav>
      {getToken() ? (
        <Routes>
          <Route path="/" element={<DigestPage />} />
          <Route path="/job/:id" element={<JobPage />} />
          <Route path="/companies" element={<CompaniesPage />} />
          <Route path="/coverage" element={<CoveragePage />} />
        </Routes>
      ) : (
        <p className="rounded bg-amber-50 p-4 text-amber-900">Open this app from the “Review” link in your digest email so it can pick up your access token.</p>
      )}
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider>
        <BrowserRouter>
          <Layout />
        </BrowserRouter>
      </ApiProvider>
    </QueryClientProvider>
  );
}
