import { File, UploadType } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';

const WORKER_BASE_URL = "https://antigravity-pairing-broker.rangsarn.workers.dev"; // Default central resolver URL
const MULTI_SERVER_CONFIG_KEY = "kookai_multi_server_config";

export interface ConnectionInfo {
  hostId: string;
  url: string;
  localIp: string;
  token?: string;
}

export interface ServerNode {
  id: string; // Unique UUID or hostId
  name: string; // Alias name (e.g. "Office PC", "Home Mac")
  hostId: string; // Host ID from Broker
  url: string; // Cloudflare / WAN Public URL
  localIp: string; // IP Address in LAN
  port: number; // Default 8080
  token: string; // JWT Auth Token
  createdAt: number; // Timestamp
  lastActive: number; // Timestamp
  connectionState: 'local' | 'wan' | 'offline';
  latency?: number; // Latency in ms
}

export interface MultiServerConfig {
  activeServerId: string | null;
  servers: Record<string, ServerNode>;
}

// In-memory cache for active base URLs per server ID
const cachedActiveBaseUrls: Record<string, string> = {};

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

/**
 * Task 1.2: Data Migration from Single-Server to Multi-Server
 */
export async function migrateLegacyConnection(): Promise<MultiServerConfig> {
  try {
    const existingConfigRaw = await SecureStore.getItemAsync(MULTI_SERVER_CONFIG_KEY);
    if (existingConfigRaw) {
      const parsed: MultiServerConfig = JSON.parse(existingConfigRaw);
      if (parsed && typeof parsed === 'object' && parsed.servers) {
        return parsed;
      }
    }

    // Check for legacy connection keys
    const hostId = (await SecureStore.getItemAsync('host_id')) || (await SecureStore.getItemAsync('kookai_host_id'));
    const url = (await SecureStore.getItemAsync('url')) || (await SecureStore.getItemAsync('kookai_server_url'));
    const localIp = (await SecureStore.getItemAsync('local_ip')) || (await SecureStore.getItemAsync('kookai_local_ip'));
    const token = (await SecureStore.getItemAsync('auth_token')) || (await SecureStore.getItemAsync('kookai_token'));

    if (hostId && url && localIp) {
      const serverId = hostId || `server_${Date.now()}`;
      const legacyServerNode: ServerNode = {
        id: serverId,
        name: 'Primary Host',
        hostId,
        url,
        localIp,
        port: 8080,
        token: token || '',
        createdAt: Date.now(),
        lastActive: Date.now(),
        connectionState: 'offline',
      };

      const newConfig: MultiServerConfig = {
        activeServerId: serverId,
        servers: {
          [serverId]: legacyServerNode
        }
      };

      await SecureStore.setItemAsync(MULTI_SERVER_CONFIG_KEY, JSON.stringify(newConfig));

      // Clean up legacy keys after migration
      await SecureStore.deleteItemAsync('host_id').catch(() => {});
      await SecureStore.deleteItemAsync('url').catch(() => {});
      await SecureStore.deleteItemAsync('local_ip').catch(() => {});
      await SecureStore.deleteItemAsync('auth_token').catch(() => {});
      await SecureStore.deleteItemAsync('kookai_host_id').catch(() => {});
      await SecureStore.deleteItemAsync('kookai_server_url').catch(() => {});
      await SecureStore.deleteItemAsync('kookai_local_ip').catch(() => {});
      await SecureStore.deleteItemAsync('kookai_token').catch(() => {});

      return newConfig;
    }
  } catch (err) {
    console.error("Migration error:", err);
  }

  const emptyConfig: MultiServerConfig = {
    activeServerId: null,
    servers: {}
  };
  await SecureStore.setItemAsync(MULTI_SERVER_CONFIG_KEY, JSON.stringify(emptyConfig));
  return emptyConfig;
}

/**
 * Task 1.3: Storage Helper APIs
 */
export async function getMultiServerConfig(): Promise<MultiServerConfig> {
  const raw = await SecureStore.getItemAsync(MULTI_SERVER_CONFIG_KEY);
  if (!raw) {
    return migrateLegacyConnection();
  }
  try {
    const config: MultiServerConfig = JSON.parse(raw);
    if (!config || typeof config !== 'object' || !config.servers) {
      return migrateLegacyConnection();
    }
    return config;
  } catch {
    return migrateLegacyConnection();
  }
}

export async function saveMultiServerConfig(config: MultiServerConfig): Promise<void> {
  await SecureStore.setItemAsync(MULTI_SERVER_CONFIG_KEY, JSON.stringify(config));
}

export async function getSavedServers(): Promise<ServerNode[]> {
  const config = await getMultiServerConfig();
  return Object.values(config.servers);
}

export async function getActiveServer(): Promise<ServerNode | null> {
  const config = await getMultiServerConfig();
  if (config.activeServerId && config.servers[config.activeServerId]) {
    return config.servers[config.activeServerId];
  }
  const servers = Object.values(config.servers);
  if (servers.length > 0) {
    // Sort by last active descending
    servers.sort((a, b) => (b.lastActive || 0) - (a.lastActive || 0));
    return servers[0];
  }
  return null;
}

export async function setActiveServerId(serverId: string): Promise<void> {
  const config = await getMultiServerConfig();
  if (config.servers[serverId]) {
    config.activeServerId = serverId;
    config.servers[serverId].lastActive = Date.now();
    await saveMultiServerConfig(config);
    delete cachedActiveBaseUrls[serverId];
  }
}

export async function saveServer(server: ServerNode, setAsActive = true): Promise<ServerNode> {
  const config = await getMultiServerConfig();

  // Find if server with same hostId already exists (if id doesn't match directly)
  let existingId = server.id;
  if (!config.servers[existingId]) {
    const found = Object.values(config.servers).find(s => s.hostId === server.hostId);
    if (found) {
      existingId = found.id;
    }
  }

  const updatedServerNode: ServerNode = {
    ...server,
    id: existingId || server.id || server.hostId || `server_${Date.now()}`,
    name: server.name || (config.servers[existingId]?.name || `Host ${server.hostId.substring(0, 6)}`),
    port: server.port || 8080,
    createdAt: config.servers[existingId]?.createdAt || server.createdAt || Date.now(),
    lastActive: Date.now(),
  };

  config.servers[updatedServerNode.id] = updatedServerNode;
  if (setAsActive || !config.activeServerId) {
    config.activeServerId = updatedServerNode.id;
  }

  await saveMultiServerConfig(config);
  delete cachedActiveBaseUrls[updatedServerNode.id];
  return updatedServerNode;
}

export async function updateServerAlias(serverId: string, newName: string): Promise<void> {
  const config = await getMultiServerConfig();
  if (config.servers[serverId]) {
    config.servers[serverId].name = newName.trim() || config.servers[serverId].name;
    await saveMultiServerConfig(config);
  }
}

export async function removeServer(serverId: string): Promise<void> {
  const config = await getMultiServerConfig();
  if (config.servers[serverId]) {
    delete config.servers[serverId];
    delete cachedActiveBaseUrls[serverId];
    if (config.activeServerId === serverId) {
      const remaining = Object.values(config.servers);
      if (remaining.length > 0) {
        remaining.sort((a, b) => (b.lastActive || 0) - (a.lastActive || 0));
        config.activeServerId = remaining[0].id;
      } else {
        config.activeServerId = null;
      }
    }
    await saveMultiServerConfig(config);
  }
}

// Legacy helper functions for backward compatibility
export async function saveConnection(info: ConnectionInfo, aliasName?: string): Promise<void> {
  const config = await getMultiServerConfig();
  const existing = Object.values(config.servers).find(s => s.hostId === info.hostId);

  const serverNode: ServerNode = {
    id: existing?.id || info.hostId || `server_${Date.now()}`,
    name: aliasName || existing?.name || `Host-${info.hostId.substring(0, 6)}`,
    hostId: info.hostId,
    url: info.url,
    localIp: info.localIp,
    port: 8080,
    token: info.token || existing?.token || '',
    createdAt: existing?.createdAt || Date.now(),
    lastActive: Date.now(),
    connectionState: existing?.connectionState || 'offline',
  };

  await saveServer(serverNode, true);
}

export async function loadConnection(): Promise<ConnectionInfo | null> {
  const active = await getActiveServer();
  if (!active || !active.token) {
    return null;
  }
  return {
    hostId: active.hostId,
    url: active.url,
    localIp: active.localIp,
    token: active.token
  };
}

export async function clearConnection(): Promise<void> {
  const config = await getMultiServerConfig();
  if (config.activeServerId) {
    await removeServer(config.activeServerId);
  }
}

/**
 * Task 2.1 & 2.2: Dynamic Routing & Real-time Health Ping
 */

// Test connectivity to a specific URL (Pinging `/api/projects`)
async function testUrl(baseUrl: string, token: string, timeoutMs = 2000): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
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

export async function getActiveBaseUrlForServer(server: ServerNode, forceRefresh = false): Promise<string | null> {
  if (!server || !server.token) return null;

  if (cachedActiveBaseUrls[server.id] && !forceRefresh) {
    return cachedActiveBaseUrls[server.id];
  }

  const port = server.port || 8080;

  // 1. Try local LAN IP (2000 ms)
  const localBase = `http://${server.localIp}:${port}`;
  const isLocalOk = await testUrl(localBase, server.token, 2000);
  if (isLocalOk) {
    console.log(`[${server.name}] Routing via Local LAN:`, localBase);
    cachedActiveBaseUrls[server.id] = localBase;
    if (server.connectionState !== 'local') {
      server.connectionState = 'local';
      await saveServer(server, false);
    }
    return localBase;
  }

  // 2. Try stored WAN / Cloudflare Tunnel URL (4000 ms)
  if (server.url) {
    const isWanOk = await testUrl(server.url, server.token, 4000);
    if (isWanOk) {
      console.log(`[${server.name}] Routing via public WAN:`, server.url);
      cachedActiveBaseUrls[server.id] = server.url;
      if (server.connectionState !== 'wan') {
        server.connectionState = 'wan';
        await saveServer(server, false);
      }
      return server.url;
    }
  }

  // 3. Central Broker Resolution
  console.log(`[${server.name}] Connection failed. Resolving host URL from broker...`);
  try {
    const response = await fetch(`${WORKER_BASE_URL}/resolve-host/${server.hostId}`);
    if (response.ok) {
      const freshInfo = await response.json();
      const freshUrl = freshInfo.url;
      const freshLocalIp = freshInfo.local_ip;

      const updatedServer = {
        ...server,
        url: freshUrl || server.url,
        localIp: freshLocalIp || server.localIp,
      };

      const isFreshWanOk = await testUrl(updatedServer.url, server.token, 4000);
      if (isFreshWanOk) {
        console.log(`[${server.name}] Resolved & routed via public WAN:`, updatedServer.url);
        cachedActiveBaseUrls[server.id] = updatedServer.url;
        updatedServer.connectionState = 'wan';
        await saveServer(updatedServer, false);
        return updatedServer.url;
      }
    }
  } catch (err) {
    console.error(`[${server.name}] Registry resolution error:`, err);
  }

  server.connectionState = 'offline';
  await saveServer(server, false);
  return null;
}

export async function pingServer(server: ServerNode): Promise<{ state: 'local' | 'wan' | 'offline'; latency?: number; activeUrl?: string }> {
  const startTime = Date.now();
  const port = server.port || 8080;

  // LAN check
  const localBase = `http://${server.localIp}:${port}`;
  const isLocal = await testUrl(localBase, server.token, 2000);
  if (isLocal) {
    const latency = Date.now() - startTime;
    cachedActiveBaseUrls[server.id] = localBase;
    server.connectionState = 'local';
    server.latency = latency;
    await saveServer(server, false);
    return { state: 'local', latency, activeUrl: localBase };
  }

  // WAN check
  if (server.url) {
    const isWan = await testUrl(server.url, server.token, 4000);
    if (isWan) {
      const latency = Date.now() - startTime;
      cachedActiveBaseUrls[server.id] = server.url;
      server.connectionState = 'wan';
      server.latency = latency;
      await saveServer(server, false);
      return { state: 'wan', latency, activeUrl: server.url };
    }
  }

  server.connectionState = 'offline';
  server.latency = undefined;
  await saveServer(server, false);
  return { state: 'offline' };
}

export async function pingAllServers(): Promise<Record<string, { state: 'local' | 'wan' | 'offline'; latency?: number }>> {
  const servers = await getSavedServers();
  const results: Record<string, { state: 'local' | 'wan' | 'offline'; latency?: number }> = {};

  await Promise.allSettled(
    servers.map(async (server) => {
      const res = await pingServer(server);
      results[server.id] = { state: res.state, latency: res.latency };
    })
  );

  return results;
}

export async function getActiveBaseUrl(info?: ConnectionInfo | null, forceRefresh = false): Promise<string | null> {
  if (info) {
    // If info is passed explicitly, attempt lookup matching hostId or resolve directly
    const config = await getMultiServerConfig();
    const server = Object.values(config.servers).find(s => s.hostId === info.hostId);
    if (server) {
      return getActiveBaseUrlForServer(server, forceRefresh);
    }
    // Fallback info ServerNode
    const tempNode: ServerNode = {
      id: info.hostId,
      name: 'Temp Host',
      hostId: info.hostId,
      url: info.url,
      localIp: info.localIp,
      port: 8080,
      token: info.token || '',
      createdAt: Date.now(),
      lastActive: Date.now(),
      connectionState: 'offline',
    };
    return getActiveBaseUrlForServer(tempNode, forceRefresh);
  }

  const active = await getActiveServer();
  if (!active) return null;
  return getActiveBaseUrlForServer(active, forceRefresh);
}

/**
 * Task 2.3: apiCall & uploadMedia updated for Multi-Server Context
 */
export async function apiCall(endpoint: string, options: RequestInit = {}, targetServerId?: string): Promise<any> {
  const config = await getMultiServerConfig();
  const server = targetServerId && config.servers[targetServerId] 
    ? config.servers[targetServerId] 
    : await getActiveServer();

  if (!server || !server.token) {
    throw new Error("No paired connection found for active server");
  }

  let baseUrl = await getActiveBaseUrlForServer(server);
  if (!baseUrl) {
    throw new Error(`Cannot reach server "${server.name}" (both LAN and Internet failed)`);
  }

  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${server.token}`,
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
        console.warn(`[${server.name}] Received 401 Unauthorized - Token may be revoked or expired.`);
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

    console.log(`[${server.name}] Request failed, retrying with forced fresh URL resolution...`, err);
    delete cachedActiveBaseUrls[server.id];
    baseUrl = await getActiveBaseUrlForServer(server, true);
    if (!baseUrl) {
      throw new Error(`Cannot reach server "${server.name}" after retry`);
    }

    const response = await fetch(`${baseUrl}${endpoint}`, {
      ...options,
      headers
    });

    if (!response.ok) {
      if (response.status === 401) {
        console.warn(`[${server.name}] Received 401 Unauthorized on retry`);
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
    throw new Error(`Upload failed: ${response.status}`);
  }

  return JSON.parse(response.body);
}

export async function uploadMedia(uri: string, filename: string, conversationId: string, targetServerId?: string): Promise<any> {
  const config = await getMultiServerConfig();
  const server = targetServerId && config.servers[targetServerId] 
    ? config.servers[targetServerId] 
    : await getActiveServer();

  if (!server || !server.token) {
    throw new Error("No paired connection found");
  }

  let baseUrl = await getActiveBaseUrlForServer(server);
  if (!baseUrl) {
    throw new Error(`Cannot reach server "${server.name}" (both LAN and Internet failed)`);
  }

  try {
    return await uploadMediaToBaseUrl(baseUrl, server.token, uri, filename, conversationId);
  } catch (err) {
    console.log(`[${server.name}] Media upload failed, retrying with fresh base URL resolution...`, err);
    delete cachedActiveBaseUrls[server.id];
    baseUrl = await getActiveBaseUrlForServer(server, true);
    if (!baseUrl) {
      throw new Error(`Cannot reach server "${server.name}" after retry`);
    }
    return uploadMediaToBaseUrl(baseUrl, server.token, uri, filename, conversationId);
  }
}
