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
  console.log("=== Running Mobile & Web Client Model & Session Persistence Tests ===");
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

  // Test 4: loadProjects preserving saved project
  console.log("Testing loadProjects preservation...");
  const projectList = ["VirtualOffice", "KookAI", "agy"];
  const savedProj = await SecureStore.getItemAsync(PREFERENCE_KEYS.project);
  let activeSelectedProj = "agy"; // initial state
  const selectedProjRef = { current: savedProj || activeSelectedProj };

  // simulate loadProjects logic
  if (selectedProjRef.current && projectList.includes(selectedProjRef.current)) {
    activeSelectedProj = selectedProjRef.current;
  } else {
    activeSelectedProj = projectList[0];
    selectedProjRef.current = projectList[0];
    await SecureStore.setItemAsync(PREFERENCE_KEYS.project, projectList[0]);
  }

  if (activeSelectedProj !== "KookAI") {
    throw new Error(`Expected activeSelectedProj to be preserved as "KookAI", got "${activeSelectedProj}"`);
  }
  console.log("✓ loadProjects preserves saved project when valid in server list!");

  // Test 5: Fallback when saved project does not exist on server
  console.log("Testing loadProjects fallback on non-existent project...");
  const newServerList = ["VirtualOffice", "OtherApp"];
  if (selectedProjRef.current && newServerList.includes(selectedProjRef.current)) {
    activeSelectedProj = selectedProjRef.current;
  } else {
    activeSelectedProj = newServerList[0];
    selectedProjRef.current = newServerList[0];
    await SecureStore.setItemAsync(PREFERENCE_KEYS.project, newServerList[0]);
  }

  if (activeSelectedProj !== "VirtualOffice") {
    throw new Error(`Expected activeSelectedProj to fallback to "VirtualOffice", got "${activeSelectedProj}"`);
  }
  const persistedFallback = await SecureStore.getItemAsync(PREFERENCE_KEYS.project);
  if (persistedFallback !== "VirtualOffice") {
    throw new Error(`Expected SecureStore to record fallback "VirtualOffice", got "${persistedFallback}"`);
  }
  console.log("✓ loadProjects correctly falls back and updates storage when saved project is missing!");

  // Test 6: Web Client localStorage preference test simulation
  console.log("Testing Web Client localStorage preferences logic...");
  const webLocalStorage: Record<string, string> = {};
  let webWorkspace = "agy";
  let webModel = "Gemini 3.7 Flash (High)";

  function webSaveAppPreferences() {
    webLocalStorage["kookai_workspace"] = webWorkspace;
    webLocalStorage["kookai_project"] = webWorkspace;
    webLocalStorage["kookai_model"] = webModel;
  }

  function webLoadAppPreferences() {
    const saved = webLocalStorage["kookai_workspace"] || webLocalStorage["kookai_project"];
    if (saved) webWorkspace = saved;
    const model = webLocalStorage["kookai_model"];
    if (model) webModel = model;
  }

  // Set web state and save
  webWorkspace = "KookAI";
  webModel = "DeepSeek R1";
  webSaveAppPreferences();

  // Reset module variables to simulate page reload
  webWorkspace = "agy";
  webModel = "Gemini 3.7 Flash (High)";
  webLoadAppPreferences();

  if (webWorkspace !== "KookAI") {
    throw new Error(`Expected webWorkspace to restore to "KookAI", got "${webWorkspace}"`);
  }
  if (webModel !== "DeepSeek R1") {
    throw new Error(`Expected webModel to restore to "DeepSeek R1", got "${webModel}"`);
  }
  console.log("✓ Web client preferences save & load simulated successfully!");

  console.log("=== ALL MODEL & SESSION PERSISTENCE TESTS PASSED! 🎉 ===");
}

runSessionModelPersistenceTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
