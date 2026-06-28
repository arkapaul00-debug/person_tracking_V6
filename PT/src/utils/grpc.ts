// src/utils/grpc.ts
//
// gRPC-Web client setup for SENTINEL PRO.
// This module provides a configured gRPC-Web client that can be used
// for high-performance binary communication with the backend AI services.
//
// Usage: Import the client instance and call generated service methods.
// Proto-generated stubs should be placed in src/utils/ alongside this file.

import { GrpcWebClientBase } from 'grpc-web';

const GRPC_ENDPOINT = import.meta.env.VITE_GRPC_ENDPOINT;

// Singleton gRPC-Web client
let grpcClient: GrpcWebClientBase | null = null;

export function getGrpcClient(): GrpcWebClientBase {
  if (!grpcClient) {
    grpcClient = new GrpcWebClientBase({
      format: 'binary',
    });
  }
  return grpcClient;
}

export function getGrpcEndpoint(): string {
  return GRPC_ENDPOINT;
}

// Helper to create metadata with auth token
export function createGrpcMetadata(
  token: string,
): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
  };
}
