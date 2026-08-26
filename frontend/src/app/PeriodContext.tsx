import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { PeriodView } from "../api/types";
import type { PeriodSelection } from "./period";

export interface PeriodControlValue {
  period: Pick<PeriodView, "year" | "month" | "label">;
  pending: PeriodSelection | null;
  loading: boolean;
  error: string | null;
  onChange: (period: PeriodSelection) => void;
}

const PeriodControlContext = createContext<PeriodControlValue | null>(null);

export function PeriodControlProvider({
  value,
  children,
}: {
  value: PeriodControlValue;
  children: ReactNode;
}) {
  return (
    <PeriodControlContext.Provider value={value}>
      {children}
    </PeriodControlContext.Provider>
  );
}

export function usePeriodControl(): PeriodControlValue | null {
  return useContext(PeriodControlContext);
}
