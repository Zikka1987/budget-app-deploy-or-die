import React, { createContext, useCallback, useContext, useState } from 'react';

interface MonthState {
  year: number;
  month: number; // 1-indexed (1–12)
}

interface MonthContextValue extends MonthState {
  setMonth: (year: number, month: number) => void;
  prevMonth: () => void;
  nextMonth: () => void;
}

const MonthContext = createContext<MonthContextValue | null>(null);

function getInitialMonth(): MonthState {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

export function MonthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<MonthState>(getInitialMonth);

  const setMonth = useCallback((year: number, month: number) => {
    setState({ year, month });
  }, []);

  const prevMonth = useCallback(() => {
    setState((p) => {
      if (p.month === 1) return { year: p.year - 1, month: 12 };
      return { ...p, month: p.month - 1 };
    });
  }, []);

  const nextMonth = useCallback(() => {
    setState((p) => {
      if (p.month === 12) return { year: p.year + 1, month: 1 };
      return { ...p, month: p.month + 1 };
    });
  }, []);

  return (
    <MonthContext.Provider value={{ ...state, setMonth, prevMonth, nextMonth }}>
      {children}
    </MonthContext.Provider>
  );
}

export function useSelectedMonth(): MonthContextValue {
  const ctx = useContext(MonthContext);
  if (!ctx) throw new Error('useSelectedMonth must be used within MonthProvider');
  return ctx;
}
