const Module = require('module');
const originalRequire = Module.prototype.require;

// Memory store for mocking expo-secure-store
const mockSecureStore = {};
const mockFetchResponses = {};

// Mock expo-secure-store and expo-file-system
Module.prototype.require = function (request) {
  if (request === 'expo-secure-store') {
    return {
      getItemAsync: async (key) => mockSecureStore[key] || null,
      setItemAsync: async (key, value) => {
        mockSecureStore[key] = value;
      },
      deleteItemAsync: async (key) => {
        delete mockSecureStore[key];
      }
    };
  }
  if (request === 'expo-file-system') {
    return {
      File: class MockFile {
        constructor(uri) { this.uri = uri; }
        upload = async () => ({ status: 200, body: JSON.stringify({ ok: true }) });
      },
      UploadType: { BINARY_CONTENT: 'BINARY_CONTENT' }
    };
  }
  return originalRequire.apply(this, arguments);
};

// Mock fetch
globalThis.fetch = async (url, options = {}) => {
  if (url.includes('/resolve-host/')) {
    const hostId = url.split('/resolve-host/')[1];
    if (mockFetchResponses[`resolve:${hostId}`]) {
      return {
        ok: true,
        status: 200,
        json: async () => mockFetchResponses[`resolve:${hostId}`]
      };
    }
  }

  if (url.includes('/api/projects')) {
    const tokenHeader = options?.headers?.['Authorization'] || '';
    if (tokenHeader.includes('invalid_token')) {
      return {
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: async () => ({ detail: 'Token invalid or expired' })
      };
    }
    if (url.includes('192.168.1.99') || url.includes('offline-server.com')) {
      throw new Error('Network error / connection refused');
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ projects: ['agy', 'kookai-mobile'] })
    };
  }

  return {
    ok: true,
    status: 200,
    json: async () => ({})
  };
};

async function runTests() {
  console.log("=== Running Multi-Server Task Integration Tests ===");

  const api = require('../utils/api');

  // Test 6.1: Data Migration (Legacy Single-Server -> Multi-Server)
  console.log("Testing Task 1.2: Data Migration...");
  mockSecureStore['host_id'] = 'host_legacy_123';
  mockSecureStore['url'] = 'https://legacy-tunnel.trycloudflare.com';
  mockSecureStore['local_ip'] = '192.168.1.50';
  mockSecureStore['auth_token'] = 'token_legacy_abc';

  const migratedConfig = await api.migrateLegacyConnection();
  if (migratedConfig.activeServerId !== 'host_legacy_123') {
    throw new Error(`Migration failed: expected activeServerId host_legacy_123, got ${migratedConfig.activeServerId}`);
  }
  if (!migratedConfig.servers['host_legacy_123']) {
    throw new Error('Migration failed: legacy server not stored');
  }
  if (migratedConfig.servers['host_legacy_123'].name !== 'Primary Host') {
    throw new Error('Migration failed: server name should default to "Primary Host"');
  }
  if (mockSecureStore['host_id']) {
    throw new Error('Migration failed: legacy keys were not cleaned up');
  }
  console.log("✓ Task 1.2 Data Migration test passed!");

  // Test 6.2: Storage Helpers (saveServer, getSavedServers, updateServerAlias, removeServer)
  console.log("Testing Task 1.3: Storage Helpers...");

  const server2 = {
    id: 'host_office_456',
    name: 'Office Desktop',
    hostId: 'host_office_456',
    url: 'https://office-tunnel.trycloudflare.com',
    localIp: '192.168.1.88',
    port: 8080,
    token: 'token_office_789',
    createdAt: Date.now(),
    lastActive: Date.now(),
    connectionState: 'offline'
  };

  await api.saveServer(server2, false);
  const savedServers = await api.getSavedServers();
  if (savedServers.length !== 2) {
    throw new Error(`Expected 2 saved servers, got ${savedServers.length}`);
  }

  // Update alias name
  await api.updateServerAlias('host_office_456', 'Office Workstation');
  const activeOffice = (await api.getSavedServers()).find((s) => s.id === 'host_office_456');
  if (activeOffice?.name !== 'Office Workstation') {
    throw new Error(`Update alias failed: expected "Office Workstation", got "${activeOffice?.name}"`);
  }
  console.log("✓ Task 1.3 Storage Helpers test passed!");

  // Test 6.3: Per-Server Routing & Health Ping
  console.log("Testing Phase 2: Per-Server Active URL Resolution & Ping...");
  const pingRes = await api.pingServer(server2);
  if (pingRes.state !== 'local' && pingRes.state !== 'wan') {
    throw new Error(`Expected active ping state local or wan, got ${pingRes.state}`);
  }

  const pingAllRes = await api.pingAllServers();
  if (!pingAllRes['host_office_456']) {
    throw new Error('pingAllServers failed to return results for host_office_456');
  }
  console.log("✓ Phase 2 Dynamic Routing & Ping tests passed!");

  // Test 6.4: Active Server switching & Token Isolation in apiCall
  console.log("Testing Phase 5: Token & Context Isolation in apiCall...");
  await api.setActiveServerId('host_office_456');
  const activeServer = await api.getActiveServer();
  if (activeServer?.id !== 'host_office_456') {
    throw new Error(`setActiveServerId failed: expected host_office_456, got ${activeServer?.id}`);
  }

  const projectsResponse = await api.apiCall('/api/projects');
  if (!Array.isArray(projectsResponse.projects)) {
    throw new Error('apiCall failed: projects array missing');
  }

  // Test removal
  await api.removeServer('host_legacy_123');
  const remainingServers = await api.getSavedServers();
  if (remainingServers.length !== 1 || remainingServers[0].id !== 'host_office_456') {
    throw new Error('removeServer failed to remove legacy server correctly');
  }
  console.log("✓ Phase 5 Token & Context Isolation test passed!");

  console.log("=== ALL MULTI-SERVER TESTS PASSED SUCCESSFULLY! 🎉 ===");
}

runTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
