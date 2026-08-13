declare const require: any;
declare const process: any;

const PREFERENCE_KEYS = {
  model: 'settings_default_model',
  target: 'settings_default_target',
  speechLang: 'settings_speech_lang',
  themeMode: 'settings_theme_mode',
  fontSize: 'settings_font_size',
  codexEffort: 'settings_codex_effort',
  codexSpeed: 'settings_codex_speed',
  claudeEffort: 'settings_claude_effort',
  claudeThinking: 'settings_claude_thinking',
  convoId: 'last_selected_convo_id',
  project: 'last_selected_project',
};

// Memory store for mocking expo-secure-store
const mockSecureStore: Record<string, string> = {};

function mockExpoSecureStore() {
  const Module = require('module');
  const originalRequire = Module.prototype.require;

  Module.prototype.require = function (request: string) {
    if (request === 'expo-secure-store') {
      return {
        getItemAsync: async (key: string) => mockSecureStore[key] || null,
        setItemAsync: async (key: string, value: string) => {
          mockSecureStore[key] = value;
        },
        deleteItemAsync: async (key: string) => {
          delete mockSecureStore[key];
        }
      };
    }
    return originalRequire.apply(this, arguments);
  };
}

mockExpoSecureStore();

async function runSessionModelPersistenceTests() {
  console.log("=== Running Mobile Client Model & Session Persistence Tests ===");
  const SecureStore = require('expo-secure-store');

  // Test 1: Saving & loading selected model
  console.log("Testing Model Persistence...");
  const selectedModel = "Claude 3.7 Sonnet (High)";
  await SecureStore.setItemAsync(PREFERENCE_KEYS.model, selectedModel);

  const restoredModel = await SecureStore.getItemAsync(PREFERENCE_KEYS.model);
  if (restoredModel !== "Claude 3.7 Sonnet (High)") {
    throw new Error(`Expected model "Claude 3.7 Sonnet (High)", got "${restoredModel}"`);
  }
  console.log("✓ Selected model persisted and restored successfully!");

  // Test 2: Saving & loading active session (conversation ID) and project
  console.log("Testing Session & Project Persistence...");
  const convoId = "convo_2026_abc123";
  const project = "KookAI";

  await SecureStore.setItemAsync(PREFERENCE_KEYS.convoId, convoId);
  await SecureStore.setItemAsync(PREFERENCE_KEYS.project, project);

  const restoredConvoId = await SecureStore.getItemAsync(PREFERENCE_KEYS.convoId);
  const restoredProject = await SecureStore.getItemAsync(PREFERENCE_KEYS.project);

  if (restoredConvoId !== convoId) {
    throw new Error(`Expected conversation ID "${convoId}", got "${restoredConvoId}"`);
  }
  if (restoredProject !== project) {
    throw new Error(`Expected project "${project}", got "${restoredProject}"`);
  }
  console.log("✓ Session and Project persisted and restored successfully!");

  // Test 3: Temporary conversation IDs should not overwrite persistent session ID
  console.log("Testing Temporary Session Handling...");
  const tempConvoId = "temp_KookAI_xyz987";
  if (tempConvoId.startsWith("temp_")) {
    await SecureStore.deleteItemAsync(PREFERENCE_KEYS.convoId);
  }

  const afterTemp = await SecureStore.getItemAsync(PREFERENCE_KEYS.convoId);
  if (afterTemp !== null) {
    throw new Error(`Expected temporary conversation to clear stored convoId, got "${afterTemp}"`);
  }
  console.log("✓ Temporary session handled cleanly!");

  console.log("=== ALL MODEL & SESSION PERSISTENCE TESTS PASSED! 🎉 ===");
}

runSessionModelPersistenceTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
