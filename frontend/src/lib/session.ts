import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { firstName } from "./format";

export function useSignOut() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return async () => {
    await api.post("/api/auth/logout").catch(() => undefined);
    qc.clear();
    navigate("/signin");
  };
}

export function greeting(name: string, hour: number) {
  return `${hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"}, ${firstName(name)}`;
}

export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}
