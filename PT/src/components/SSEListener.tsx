// src/components/SSEListener.tsx
import { useEffect } from 'react';
import { useSentinelStore } from '@utils/store';
import { connectSSE, disconnectSSE } from '@utils/sse';

/**
 * SSEListener manages the SSE connection lifecycle.
 * It connects when a user is authenticated and disconnects on logout.
 * Renders nothing — purely a side-effect component.
 */
const SSEListener: React.FC = () => {
  const user = useSentinelStore((s) => s.user);

  useEffect(() => {
    if (user?.token) {
      connectSSE(user.token);
    } else {
      disconnectSSE();
    }

    return () => {
      disconnectSSE();
    };
  }, [user?.token]);

  return null;
};

export default SSEListener;
