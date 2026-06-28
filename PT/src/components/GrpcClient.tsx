// src/components/GrpcClient.tsx
import React, { createContext, useContext, useMemo } from 'react';
import { GrpcWebClientBase } from 'grpc-web';

interface GrpcContextValue {
  client: GrpcWebClientBase;
  endpoint: string;
}

const GrpcContext = createContext<GrpcContextValue | null>(null);

interface GrpcProviderProps {
  children: React.ReactNode;
}

export const GrpcProvider: React.FC<GrpcProviderProps> = ({ children }) => {
  const endpoint = import.meta.env.VITE_GRPC_ENDPOINT;

  const value = useMemo<GrpcContextValue>(
    () => ({
      client: new GrpcWebClientBase({ format: 'binary' }),
      endpoint,
    }),
    [endpoint],
  );

  return (
    <GrpcContext.Provider value={value}>{children}</GrpcContext.Provider>
  );
};

export function useGrpcClient(): GrpcContextValue {
  const ctx = useContext(GrpcContext);
  if (!ctx) {
    throw new Error('useGrpcClient must be used within a GrpcProvider');
  }
  return ctx;
}

export default GrpcProvider;
