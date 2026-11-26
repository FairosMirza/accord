import { createBrowserRouter } from "react-router";
import Layout from "./components/Layout";
import Approvals from "./pages/Approvals";
import Audit from "./pages/Audit";
import Cover from "./pages/Cover";
import Finance from "./pages/Finance";
import Home from "./pages/Home";
import Insights from "./pages/Insights";
import NotFound from "./pages/NotFound";
import Outbox from "./pages/Outbox";
import { ProjectDetail, Projects } from "./pages/Projects";
import RequestDetail from "./pages/RequestDetail";
import RequestForm, { AmendForm } from "./pages/RequestForm";
import Requests from "./pages/Requests";
import SignIn from "./pages/SignIn";
import Categories from "./pages/admin/Categories";
import People from "./pages/admin/People";
import Policy from "./pages/admin/Policy";
import Rates from "./pages/admin/Rates";

export const router = createBrowserRouter([
  { path: "/signin", element: <SignIn /> },
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      { path: "approvals", element: <Approvals /> },
      { path: "requests", element: <Requests /> },
      { path: "requests/new", element: <RequestForm /> },
      { path: "requests/:ref", element: <RequestDetail /> },
      { path: "requests/:ref/edit", element: <RequestForm /> },
      { path: "requests/:ref/change", element: <AmendForm /> },
      { path: "projects", element: <Projects /> },
      { path: "projects/:id", element: <ProjectDetail /> },
      { path: "finance", element: <Finance /> },
      { path: "insights", element: <Insights /> },
      { path: "cover", element: <Cover /> },
      { path: "audit", element: <Audit /> },
      { path: "outbox", element: <Outbox /> },
      { path: "settings/policy", element: <Policy /> },
      { path: "settings/categories", element: <Categories /> },
      { path: "settings/rates", element: <Rates /> },
      { path: "settings/people", element: <People /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
