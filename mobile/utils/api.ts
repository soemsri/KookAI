import { File, UploadType } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';

const WORKER_BASE_URL = "https://antigravity-pairing-broker.rangsarn.workers.dev"; // Default central resolver URL

export interface ConnectionInfo {
  hostId: string;
  url: string;
  localIp: string;
  token?: string;
}

// In-memory cache for the active base URL to avoid pinging LAN and WAN on every single API call
let cachedActiveBaseUrl: string | null = null;

async function createApiError(response: Response): Promise<Error> {
  let detail = '';
  try {
    const payload = await response.json();
    detail = typeof payload?.detail === 'string' ? payload.detail : '';
  } catch {
    // The host may return an empty or non-JSON error response.
  }

  const error = new Error(
    detail || `API error: ${response.status} ${response.statusText}`
  );
  (error as Error & { status?: number }).status = response.status;
  return error;
}

// Save connection info securely
export async function saveConnection(info: ConnectionInfo) {
  await SecureStore.setItemAsync('host_id', info.hostId);
  await SecureStore.setItemAsync('url', info.url);
  await SecureStore.setItemAsync('local_ip', info.localIp);
  if (info.token) {
    await SecureStore.setItemAsync('auth_token', info.token);
  }
  // Clear cache to force a re-evaluation on next call
  cachedActiveBaseUrl = null;
}

// Load saved connection
export async function loadConnection(): Promise<ConnectionInfo | null> {
  const hostId = await SecureStore.getItemAsync('host_id');
  const url = await SecureStore.getItemAsync('url');
  const localIp = await SecureStore.getItemAsync('local_ip');
  const token = await SecureStore.getItemAsync('auth_token') || undefined;
  
  if (!hostId || !url || !localIp) {
    return null;
  }
  return { hostId, url, localIp, token };
}

// Clear connection (Logout)
export async function clearConnection() {
  await SecureStore.deleteItemAsync('host_id');
  await SecureStore.deleteItemAsync('url');
  await SecureStore.deleteItemAsync('local_ip');
  await SecureStore.deleteItemAsync('auth_token');
  cachedActiveBaseUrl = null;
}

// Test connectivity to a specific URL (Pinging `/api/projects`)
async function testUrl(baseUrl: string, token: string, timeoutMs = 2000): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs); // configurable timeout
    const response = await fetch(`${baseUrl}/api/projects`, {
      headers: { 
        'Authorization': `Bearer ${token}`,
        'Bypass-Tunnel-Reminder': 'true'
      },
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return response.status === 200;
  } catch {
    return false;
  }
}

// Resolve the active base URL dynamically (LAN first, then WAN/Tunnel)
export async function getActiveBaseUrl(info: ConnectionInfo, forceRefresh = false): Promise<string | null> {
  if (!info.token) return null;

  // Use cached URL if available and refresh is not forced
  if (cachedActiveBaseUrl && !forceRefresh) {
    return cachedActiveBaseUrl;
  }

  // 1. Try local LAN IP
  const localBase = `http://${info.localIp}:8080`;
  const isLocalOk = await testUrl(localBase, info.token, 2000); // 2s timeout is fine for LAN
  if (isLocalOk) {
    console.log("Routing via Local LAN:", localBase);
    cachedActiveBaseUrl = localBase;
    return localBase;
  }

  // 2. Try stored WAN / Cloudflare Tunnel URL
  const isWanOk = await testUrl(info.url, info.token, 5000); // 5s timeout for public WAN
  if (isWanOk) {
    console.log("Routing via public WAN:", info.url);
    cachedActiveBaseUrl = info.url;
    return info.url;
  }

  // 3. Both failed! Try to resolve fresh URL from Worker registry
  console.log("Connection failed. Resolving new host URL from registry...");
  try {
    const response = await fetch(`${WORKER_BASE_URL}/resolve-host/${info.hostId}`);
    if (response.ok) {
      const freshInfo = await response.json();
      const freshUrl = freshInfo.url;
      const freshLocalIp = freshInfo.local_ip;
      
      // Update local cache
      const updatedInfo = { ...info, url: freshUrl, localIp: freshLocalIp };
      await saveConnection(updatedInfo);
      
      // Test the newly resolved URL
      const isFreshWanOk = await testUrl(freshUrl, info.token, 5000); // 5s timeout for public WAN
      if (isFreshWanOk) {
        console.log("Successfully resolved and routed via public WAN:", freshUrl);
        cachedActiveBaseUrl = freshUrl;
        return freshUrl;
      }
    }
  } catch (err) {
    console.error("Failed to resolve host from registry:", err);
  }

  return null;
}

// Generic API caller with token auth and dynamic routing
export async function apiCall(endpoint: string, options: RequestInit = {}): Promise<any> {
  const info = await loadConnection();
  if (!info || !info.token) {
    throw new Error("No paired connection found");
  }

  let baseUrl = await getActiveBaseUrl(info);
  if (!baseUrl) {
    throw new Error("Cannot reach host computer (both LAN and Internet failed)");
  }

  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${info.token}`,
    'Content-Type': 'application/json',
    'Bypass-Tunnel-Reminder': 'true'
  };

  try {
    const response = await fetch(`${baseUrl}${endpoint}`, {
      ...options,
      headers
    });

    if (!response.ok) {
      if (response.status === 401) {
        await clearConnection(); // Token revoked, force repair
      }
      throw await createApiError(response);
    }

    return response.json();
  } catch (err) {
    if (options.signal?.aborted || (err instanceof Error && err.name === 'AbortError')) {
      throw err;
    }
    const status = (err as Error & { status?: number })?.status;
    if (status !== undefined && status < 500) {
      throw err;
    }

    // If the request failed, it might be due to a change in the server's public URL/IP.
    // Try resolving a fresh URL from the registry once!
    console.log("Request failed, retrying with fresh base URL resolution...", err);
    cachedActiveBaseUrl = null;
    baseUrl = await getActiveBaseUrl(info, true);
    if (!baseUrl) {
      throw new Error("Cannot reach host computer after retry");
    }

    const response = await fetch(`${baseUrl}${endpoint}`, {
      ...options,
      headers
    });

    if (!response.ok) {
      if (response.status === 401) {
        await clearConnection();
      }
      throw await createApiError(response);
    }

    return response.json();
  }
}

async function uploadMediaToBaseUrl(baseUrl: string, token: string, uri: string, filename: string, conversationId: string) {
  const uploadUrl = `${baseUrl}/api/upload-media?conversation_id=${encodeURIComponent(conversationId)}&filename=${encodeURIComponent(filename)}`;
  const file = new File(uri);
  const response = await file.upload(uploadUrl, {
    httpMethod: 'POST',
    uploadType: UploadType.BINARY_CONTENT,
    mimeType: 'application/octet-stream',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/octet-stream',
      'Bypass-Tunnel-Reminder': 'true'
    }
  });

  if (response.status < 200 || response.status >= 300) {
    if (response.status === 401) {
      await clearConnection();
    }
    throw new Error(`Upload failed: ${response.status}`);
  }

  return JSON.parse(response.body);
}

export async function uploadMedia(uri: string, filename: string, conversationId: string): Promise<any> {
  const info = await loadConnection();
  if (!info || !info.token) {
    throw new Error("No paired connection found");
  }

  let baseUrl = await getActiveBaseUrl(info);
  if (!baseUrl) {
    throw new Error("Cannot reach host computer (both LAN and Internet failed)");
  }

  try {
    return await uploadMediaToBaseUrl(baseUrl, info.token, uri, filename, conversationId);
  } catch (err) {
    console.log("Media upload failed, retrying with fresh base URL resolution...", err);
    cachedActiveBaseUrl = null;
    baseUrl = await getActiveBaseUrl(info, true);
    if (!baseUrl) {
      throw new Error("Cannot reach host computer after retry");
    }
    return uploadMediaToBaseUrl(baseUrl, info.token, uri, filename, conversationId);
  }
}
