document.addEventListener("DOMContentLoaded", () => {
  // UI Panels
  const chatPanel = document.getElementById("chatPanel");
  const historyPanel = document.getElementById("historyPanel");

  // Tab Menu elements
  const historyMenuBtn = document.getElementById("historyMenuBtn");
  const newConvoBtn = document.getElementById("newConvoBtn");
  const headerProject = document.getElementById("headerProject");
  const headerConvo = document.getElementById("headerConvo");

  // Mobile Sidebar Controls
  const mobileSidebarToggle = document.getElementById("mobileSidebarToggle");
  const mobileHistorySidebarToggle = document.getElementById("mobileHistorySidebarToggle");
  const sidebarCloseBtn = document.getElementById("sidebarCloseBtn");
  const sidebarBackdrop = document.getElementById("sidebarBackdrop");
  const sidebar = document.querySelector(".sidebar");

  function openMobileSidebar() {
    if (sidebar) sidebar.classList.add("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("hidden");
  }

  function closeMobileSidebar() {
    if (sidebar) sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.add("hidden");
  }

  function autoCloseMobileSidebar() {
    if (window.innerWidth <= 1024) {
      closeMobileSidebar();
    }
  }

  if (mobileSidebarToggle) mobileSidebarToggle.addEventListener("click", openMobileSidebar);
  if (mobileHistorySidebarToggle) mobileHistorySidebarToggle.addEventListener("click", openMobileSidebar);
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener("click", closeMobileSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener("click", closeMobileSidebar);

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1024) {
      closeMobileSidebar();
    }
  });

  // Chat Panel UI Elements
  const promptTextarea = document.getElementById("promptTextarea");
  const sendBtn = document.getElementById("sendBtn");
  const plusBtn = document.getElementById("plusBtn");
  const micBtn = document.getElementById("micBtn");
  const welcomeScreen = document.getElementById("welcomeScreen");
  const messagesContainer = document.getElementById("messagesContainer");
  const chatScroll = document.getElementById("chatScroll");
  const autocompletePopup = document.getElementById("autocompletePopup");

  // History Panel UI Elements
  const historyList = document.getElementById("historyList");
  const historySearchInput = document.getElementById("historySearchInput");

  // Tool Dropdown Buttons
  const modelBtn = document.getElementById("modelBtn");
  const codexEffortBtn = document.getElementById("codexEffortBtn");
  const codexSpeedBtn = document.getElementById("codexSpeedBtn");
  const targetBtn = document.getElementById("targetBtn");
  const projectPickerBtn = document.getElementById("projectPickerBtn");

  // Dropdown Menus
  const workspaceDropdown = document.getElementById("workspaceDropdown");
  const modelDropdown = document.getElementById("modelDropdown");
  const codexEffortDropdown = document.getElementById("codexEffortDropdown");
  const codexSpeedDropdown = document.getElementById("codexSpeedDropdown");
  const claudeEffortDropdown = document.getElementById("claudeEffortDropdown");
  const targetDropdown = document.getElementById("targetDropdown");

  // Display texts
  const currentModelText = document.getElementById("currentModelText");
  const currentCodexEffortText = document.getElementById("currentCodexEffortText");
  const currentCodexSpeedText = document.getElementById("currentCodexSpeedText");
  const codexInlineControls = document.getElementById("codexInlineControls");
  const currentTargetText = document.getElementById("currentTargetText");

  // State Variables
  let currentWorkspace = "agy";
  let currentModel = "Gemini 3.5 Flash (High)";
  let currentProvider = "agy";
  let currentCodexEffort = "Medium";
  let currentCodexSpeed = "Standard";
  let currentClaudeEffort = "Medium";
  let currentClaudeThinking = true;
  let currentTarget = "Sandbox";
  let currentThemeMode = "system";
  let activeConversationId = ""; // Current chat session ID
  let workspaceFiles = [];
  let projectsList = [];
  let conversationsList = [];
  let isRecording = false;
  let recognition = null;

  let CODEX_MODELS = {
    "5.6 Sol": { ultra: true, fast: true },
    "5.6 Terra": { ultra: true, fast: true },
    "5.6 Luna": { ultra: false, fast: true },
    "5.5": { ultra: false, fast: true },
    "5.4": { ultra: false, fast: true },
    "5.4 Mini": { ultra: false, fast: false }
  };
  let CLAUDE_MODELS = {
    "Fable 5": { effort: true, extra: true, thinkingRequired: true },
    "Opus 5": { effort: true, extra: true },
    "Sonnet 5": { effort: true, extra: true },
    "Haiku 4.5": { effort: false, extra: false },
    "Opus 4.8": { effort: true, extra: true },
    "Opus 4.7": { effort: true, extra: true },
    "Opus 4.6": { effort: true, extra: false },
    "Opus 3": { effort: false, extra: false },
    "Sonnet 4.6": { effort: true, extra: false }
  };
  let XAI_MODELS = {
    "Grok 4.6": {
      effort: true,
      efforts: ["Low", "Medium", "High"],
      extra: false,
      thinkingRequired: true
    },
    "Grok 4.5": {
      effort: true,
      efforts: ["Low", "Medium", "High"],
      extra: false,
      thinkingRequired: true
    },
    "Grok 4.20 Reasoning": { effort: false, extra: false, thinkingRequired: true },
    "Grok Build 0.1": { effort: false, extra: false, thinkingRequired: true }
  };
  let XAI_MODEL_IDS = new Set([
    "Grok 4.6",
    "Grok 4.5",
    "Grok 4.20 Reasoning",
    "Grok 4.20 Non-Reasoning",
    "Grok Build 0.1"
  ]);
  let MUSE_MODELS = {
    "Muse Spark 1.2": {
      effort: true,
      efforts: ["Low", "Medium", "High"],
      extra: false,
      thinkingRequired: true
    }
  };
  let MUSE_MODEL_IDS = new Set(["Muse Spark 1.2"]);
  let MODEL_CATALOG = {};
  let modelCatalogVersion = "built-in";
  let defaultCatalogModel = currentModel;

  const isCodexModel = model => Object.prototype.hasOwnProperty.call(CODEX_MODELS, model);
  const isClaudeModel = model => Object.prototype.hasOwnProperty.call(CLAUDE_MODELS, model);
  const isXaiModel = model =>
    getCatalogModel(model)?.provider === "xai" || XAI_MODEL_IDS.has(model);
  const isMuseModel = model =>
    getCatalogModel(model)?.provider === "muse" || MUSE_MODEL_IDS.has(model);
  const getCatalogModel = model => MODEL_CATALOG[model] || null;
  const getModelLabel = model => getCatalogModel(model)?.label || model;

  function renderModelCatalog(payload) {
    const models = Array.isArray(payload?.models)
      ? payload.models.filter(model => model?.enabled !== false)
      : [];
    if (!models.length) return false;

    const nextCatalog = {};
    const nextCodexModels = {};
    const nextClaudeModels = {};
    const nextXaiModels = {};
    const nextMuseModels = {};
    const groups = [
      ["agy", "Antigravity Models"],
      ["kimi", "Moonshot Kimi Code CLI"],
      ["xai", "xAI Grok Build CLI"],
      ["muse", "Meta Muse Code CLI"],
      ["claude", "Anthropic Claude CLI"],
      ["codex", "OpenAI Codex CLI"]
    ];

    models.forEach(model => {
      if (
        !model
        || typeof model.id !== "string"
        || typeof model.label !== "string"
        || !["agy", "claude", "codex", "kimi", "xai", "muse"].includes(model.provider)
      ) {
        return;
      }
      const capabilities = model.capabilities || {};
      const efforts = Array.isArray(capabilities.effort) ? capabilities.effort : [];
      const speeds = Array.isArray(capabilities.speed) ? capabilities.speed : [];
      nextCatalog[model.id] = model;
      if (model.provider === "codex") {
        nextCodexModels[model.id] = {
          ultra: efforts.includes("Ultra"),
          fast: speeds.includes("Fast")
        };
      } else if (model.provider === "claude") {
        nextClaudeModels[model.id] = {
          effort: efforts.length > 0,
          extra: efforts.includes("Extra"),
          thinkingRequired: capabilities.thinking_required === true
        };
      } else if (
        model.provider === "xai"
        && (efforts.length > 0 || capabilities.thinking === true)
      ) {
        nextXaiModels[model.id] = {
          effort: efforts.length > 0,
          efforts,
          extra: false,
          thinkingRequired: capabilities.thinking_required === true
        };
      } else if (
        model.provider === "muse"
        && (efforts.length > 0 || capabilities.thinking === true)
      ) {
        nextMuseModels[model.id] = {
          effort: efforts.length > 0,
          efforts,
          extra: false,
          thinkingRequired: capabilities.thinking_required === true
        };
      }
    });

    if (!Object.keys(nextCatalog).length) return false;
    MODEL_CATALOG = nextCatalog;
    CODEX_MODELS = nextCodexModels;
    CLAUDE_MODELS = nextClaudeModels;
    XAI_MODELS = nextXaiModels;
    MUSE_MODELS = nextMuseModels;
    XAI_MODEL_IDS = new Set(
      models.filter(model => model.provider === "xai").map(model => model.id)
    );
    MUSE_MODEL_IDS = new Set(
      models.filter(model => model.provider === "muse").map(model => model.id)
    );
    modelCatalogVersion = String(payload.catalog_version || "dynamic");
    defaultCatalogModel = nextCatalog[payload.default_model]
      ? payload.default_model
      : Object.keys(nextCatalog)[0];

    modelDropdown.innerHTML = groups.map(([provider, title]) => {
      const providerModels = models.filter(model => model.provider === provider && nextCatalog[model.id]);
      if (!providerModels.length) return "";
      const items = providerModels.map(model => {
        const badge = escapeHtml(model.badge || (
          provider === "codex"
            ? "Codex"
            : provider === "claude"
              ? "Claude"
              : provider === "kimi"
                ? "Kimi"
                : provider === "xai"
                  ? "Grok"
                  : provider === "muse"
                    ? "Muse"
                : "AI"
        ));
        const badgeClass = provider === "codex"
          ? "codex"
          : provider === "claude"
            ? "claude"
            : provider === "kimi"
              ? "kimi"
              : provider === "xai"
                ? "grok"
                : provider === "muse"
                  ? "muse"
            : badge.toLowerCase().replace(/[^a-z0-9_-]/g, "") || "gpt";
        return `
          <div class="dropdown-item" data-value="${escapeHtml(model.id)}">
            <span class="model-badge ${badgeClass}">${badge}</span>
            <div class="model-info">
              <span class="model-name">${escapeHtml(model.label)}</span>
              <span class="model-desc">${escapeHtml(model.description || "")}</span>
            </div>
          </div>
        `;
      }).join("");
      return `<div class="dropdown-header">${escapeHtml(title)}</div>${items}`;
    }).join("");

    settingsDefaultModel.innerHTML = models
      .filter(model => nextCatalog[model.id])
      .map(model => (
        `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}</option>`
      ))
      .join("");

    if (!nextCatalog[currentModel]) {
      currentModel = defaultCatalogModel;
    }
    settingsDefaultModel.value = currentModel;
    const diagModelCatalog = document.getElementById("diagModelCatalog");
    if (diagModelCatalog) {
      diagModelCatalog.textContent = `${modelCatalogVersion} · ${models.length} models`;
    }
    updateCodexControls();
    return true;
  }

  async function loadModelCatalog() {
    if (!canUseProtectedWorkspaceApis()) return;
    try {
      const response = await fetch("/api/models");
      if (!response.ok) throw new Error(`Failed to load model catalog (${response.status})`);
      renderModelCatalog(await response.json());
    } catch (error) {
      console.warn("Using built-in model catalog:", error);
    }
  }

  function updateCodexControls() {
    const capability = CODEX_MODELS[currentModel];
    const claudeCapability = CLAUDE_MODELS[currentModel];
    const xaiCapability = XAI_MODELS[currentModel];
    const museCapability = MUSE_MODELS[currentModel];
    const reasoningCapability = claudeCapability || xaiCapability || museCapability;
    const selectedItem = Array.from(
      modelDropdown?.querySelectorAll(".dropdown-item") || []
    ).find(item => item.dataset.value === currentModel);
    currentProvider = getCatalogModel(currentModel)?.provider
      || selectedItem?.dataset.provider
      || (capability ? "codex" : (claudeCapability ? "claude" : (xaiCapability ? "xai" : (museCapability ? "muse" : "agy"))));

    if (capability && !capability.ultra && currentCodexEffort === "Ultra") {
      currentCodexEffort = "Medium";
    }
    if (capability && !capability.fast && currentCodexSpeed === "Fast") {
      currentCodexSpeed = "Standard";
    }

    if (reasoningCapability?.thinkingRequired) currentClaudeThinking = true;
    if (reasoningCapability && !reasoningCapability.extra && currentClaudeEffort === "Extra") {
      currentClaudeEffort = "High";
    }
    const currentEfforts = xaiCapability?.efforts || museCapability?.efforts;
    if (
      currentEfforts?.length
      && !currentEfforts.includes(currentClaudeEffort)
    ) {
      currentClaudeEffort = currentEfforts.includes("Medium")
        ? "Medium"
        : currentEfforts[0];
    }

    codexInlineControls?.classList.toggle("hidden", !capability && !reasoningCapability);
    if (currentModelText) {
      const modelLabel = getModelLabel(currentModel);
      currentModelText.textContent = capability
        ? `${modelLabel} ${currentCodexEffort}`
        : (reasoningCapability?.effort ? `${modelLabel} ${currentClaudeEffort}` : modelLabel);
    }
    if (currentCodexEffortText) {
      currentCodexEffortText.textContent = reasoningCapability ? currentClaudeEffort : currentCodexEffort;
    }
    if (currentCodexSpeedText) {
      currentCodexSpeedText.textContent = reasoningCapability
        ? (currentClaudeThinking ? "On" : "Off")
        : currentCodexSpeed;
    }
    const effortLabel = codexEffortBtn?.querySelector(".codex-inline-label");
    const speedLabel = codexSpeedBtn?.querySelector(".codex-inline-label");
    const claudeEffortHeader = claudeEffortDropdown?.querySelector(".dropdown-header");
    const settingsReasoningEffortLabel = document.querySelector("#settingsClaudeEffortGroup label");
    const settingsThinkingLabel = document.querySelector("#settingsClaudeThinkingGroup label");
    if (effortLabel) effortLabel.textContent = "Effort";
    if (speedLabel) speedLabel.textContent = reasoningCapability ? "Thinking" : "Speed";
    if (claudeEffortHeader) {
      claudeEffortHeader.textContent = museCapability
        ? "Muse Reasoning Effort"
        : (xaiCapability ? "Grok Reasoning Effort" : "Claude Effort");
    }
    if (settingsReasoningEffortLabel) {
      settingsReasoningEffortLabel.textContent = museCapability
        ? "Muse Reasoning Effort"
        : (xaiCapability ? "Grok Reasoning Effort" : "Claude Effort");
    }
    if (settingsThinkingLabel) {
      settingsThinkingLabel.textContent = museCapability
        ? "Muse Reasoning"
        : (xaiCapability ? "Grok Reasoning" : "Claude Thinking");
    }
    codexEffortBtn?.classList.toggle("hidden", Boolean(reasoningCapability && !reasoningCapability.effort));
    modelDropdown?.querySelectorAll(".dropdown-item").forEach(item => {
      item.classList.toggle("active", item.dataset.value === currentModel);
    });

    codexEffortDropdown?.querySelectorAll(".dropdown-item").forEach(item => {
      const isUnsupported = item.dataset.ultraOnly === "true" && !capability?.ultra;
      item.classList.toggle("hidden", isUnsupported);
      item.classList.toggle("active", item.dataset.value === currentCodexEffort);
    });
    codexSpeedDropdown?.querySelectorAll(".dropdown-item").forEach(item => {
      const isUnsupported = item.dataset.fastOnly === "true" && !capability?.fast;
      item.classList.toggle("hidden", isUnsupported);
      item.classList.toggle("active", item.dataset.value === currentCodexSpeed);
    });
    claudeEffortDropdown?.querySelectorAll(".dropdown-item").forEach(item => {
      const isUnsupported = currentEfforts?.length
        ? !currentEfforts.includes(item.dataset.value)
        : item.dataset.extraOnly === "true" && !reasoningCapability?.extra;
      item.classList.toggle("hidden", isUnsupported);
      item.classList.toggle("active", item.dataset.value === currentClaudeEffort);
    });

    document.getElementById("settingsCodexEffortGroup")?.classList.toggle("hidden", !capability);
    document.getElementById("settingsCodexSpeedGroup")?.classList.toggle("hidden", !capability);
    document.getElementById("settingsClaudeEffortGroup")?.classList.toggle(
      "hidden",
      !reasoningCapability?.effort
    );
    document.getElementById("settingsClaudeThinkingGroup")?.classList.toggle("hidden", !reasoningCapability);
    const ultraOption = document.querySelector('#settingsCodexEffort option[value="Ultra"]');
    const fastOption = document.querySelector('#settingsCodexSpeed option[value="Fast"]');
    if (ultraOption) ultraOption.disabled = !capability?.ultra;
    if (fastOption) fastOption.disabled = !capability?.fast;
  }

  function applyModelSelection(model, startFreshOnProviderChange = false) {
    currentModel = Object.keys(MODEL_CATALOG).length && !MODEL_CATALOG[model]
      ? defaultCatalogModel
      : model;
    updateCodexControls();
    if (startFreshOnProviderChange && activeConversationId) {
      startNewConversation();
    }
  }

  // Autocomplete state
  let isSuggesting = false;
  let suggestionType = "";
  let suggestionQuery = "";
  let suggestionIndex = 0;
  let suggestionList = [];

  // Generate a random UUID
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  // --- Initialize App ---
  function applyThemeMode() {
    if (currentThemeMode === "light" || currentThemeMode === "dark") {
      document.documentElement.dataset.theme = currentThemeMode;
    } else {
      delete document.documentElement.dataset.theme;
    }
  }

  function setThemeModeControl(value) {
    const control = document.getElementById("settingsThemeMode");
    if (!control) return;
    control.querySelectorAll(".theme-segment").forEach(button => {
      const isActive = button.getAttribute("data-theme-mode") === value;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-checked", isActive ? "true" : "false");
      button.setAttribute("tabindex", isActive ? "0" : "-1");
    });
  }

  function saveAppPreferences() {
    localStorage.setItem("kookai_model", currentModel);
    localStorage.setItem("kookai_codex_effort", currentCodexEffort);
    localStorage.setItem("kookai_codex_speed", currentCodexSpeed);
    localStorage.setItem("kookai_claude_effort", currentClaudeEffort);
    localStorage.setItem("kookai_claude_thinking", currentClaudeThinking ? "true" : "false");
    localStorage.setItem("kookai_target", currentTarget);
    localStorage.setItem("kookai_theme", currentThemeMode);
  }

  function loadAppPreferences() {
    const savedModel = (localStorage.getItem("kookai_model") || localStorage.getItem("antigravity_model"));
    const savedTarget = (localStorage.getItem("kookai_target") || localStorage.getItem("antigravity_target"));
    const savedThemeMode = (localStorage.getItem("kookai_theme") || localStorage.getItem("antigravity_theme"));
    const savedCodexEffort = (localStorage.getItem("kookai_codex_effort") || localStorage.getItem("antigravity_codex_effort"));
    const savedCodexSpeed = (localStorage.getItem("kookai_codex_speed") || localStorage.getItem("antigravity_codex_speed"));
    const savedClaudeEffort = localStorage.getItem("kookai_claude_effort");
    const savedClaudeThinking = localStorage.getItem("kookai_claude_thinking");

    if (["Light", "Medium", "High", "Extra High", "Ultra"].includes(savedCodexEffort)) {
      currentCodexEffort = savedCodexEffort;
    }
    if (["Standard", "Fast"].includes(savedCodexSpeed)) {
      currentCodexSpeed = savedCodexSpeed;
    }
    if (["Low", "Medium", "High", "Extra", "Max"].includes(savedClaudeEffort)) {
      currentClaudeEffort = savedClaudeEffort;
    }
    if (savedClaudeThinking === "true" || savedClaudeThinking === "false") {
      currentClaudeThinking = savedClaudeThinking === "true";
    }

    if (savedModel && (!Object.keys(MODEL_CATALOG).length || MODEL_CATALOG[savedModel])) {
      applyModelSelection(savedModel, false);
      modelDropdown.querySelectorAll(".dropdown-item").forEach(item => {
        if (item.getAttribute("data-value") === currentModel) {
          item.classList.add("active");
        } else {
          item.classList.remove("active");
        }
      });
    } else if (Object.keys(MODEL_CATALOG).length) {
      applyModelSelection(defaultCatalogModel, false);
    }
    updateCodexControls();

    if (savedTarget) {
      currentTarget = savedTarget;
      if (currentTargetText) currentTargetText.textContent = currentTarget;
      targetDropdown.querySelectorAll(".dropdown-item").forEach(item => {
        if (item.getAttribute("data-value") === currentTarget) {
          item.classList.add("active");
        } else {
          item.classList.remove("active");
        }
      });
    }

    if (savedThemeMode === "system" || savedThemeMode === "light" || savedThemeMode === "dark") {
      currentThemeMode = savedThemeMode;
    }
    applyThemeMode();
  }

  function isLocalWebOrigin() {
    return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  }

  function canUseProtectedWorkspaceApis() {
    return isLocalWebOrigin();
  }

  function handleProtectedApiUnauthorized() {
    console.warn("Workspace API access is localhost-only for the web client.");
  }

  function loadProtectedWorkspaceData() {
    fetchUsageLimits();
    refreshUsageDisplay();
    loadProjectsAndConversations();
    fetchWorkspaceFiles();
  }

  async function initApp() {
    await loadModelCatalog();
    loadAppPreferences();
    initLocalAccessUI();
    startNewConversation(); // Generate initial UUID
    if (canUseProtectedWorkspaceApis()) {
      loadProtectedWorkspaceData();
    }
  }

  // --- Fetch Data ---
  async function fetchWorkspaceFiles() {
    if (!canUseProtectedWorkspaceApis()) return;
    try {
      const res = await fetch("/api/files");
      if (res.status === 401) {
        workspaceFiles = [];
        handleProtectedApiUnauthorized();
        return;
      }
      if (!res.ok) throw new Error(`Failed to load files (${res.status})`);
      const data = await res.json();
      workspaceFiles = Array.isArray(data.files) ? data.files : [];
    } catch (err) {
      console.error("Error loading files:", err);
      workspaceFiles = [];
    }
  }

  async function loadProjectsAndConversations() {
    if (!canUseProtectedWorkspaceApis()) {
      projectsList = [];
      conversationsList = [];
      renderProjectsTree();
      renderWorkspaceDropdown();
      return;
    }
    try {
      const projRes = await fetch("/api/projects");
      if (projRes.status === 401) {
        projectsList = [];
        conversationsList = [];
        handleProtectedApiUnauthorized();
        renderProjectsTree();
        renderWorkspaceDropdown();
        return;
      }
      if (!projRes.ok) throw new Error(`Failed to load projects (${projRes.status})`);
      const projData = await projRes.json();
      projectsList = Array.isArray(projData.projects) ? projData.projects : [];
      if (!projectsList.includes(currentWorkspace)) {
        currentWorkspace = projectsList[0] || "";
        if (headerProject) {
          headerProject.textContent = currentWorkspace || "No workspace";
        }
      }
      if (projData.workspace_dir) {
        const diagWorkspace = document.getElementById("diagWorkspace");
        if (diagWorkspace) {
          diagWorkspace.textContent = projData.workspace_dir;
        }
      }

      const convoRes = await fetch("/api/conversations");
      if (convoRes.status === 401) {
        conversationsList = [];
        handleProtectedApiUnauthorized();
        renderProjectsTree();
        renderWorkspaceDropdown();
        return;
      }
      if (!convoRes.ok) throw new Error(`Failed to load conversations (${convoRes.status})`);
      const convoData = await convoRes.json();
      conversationsList = Array.isArray(convoData.conversations) ? convoData.conversations : [];

      renderProjectsTree();
      renderWorkspaceDropdown();
    } catch (err) {
      console.error("Error loading workspace metadata:", err);
      projectsList = Array.isArray(projectsList) ? projectsList : [];
      conversationsList = Array.isArray(conversationsList) ? conversationsList : [];
      renderProjectsTree();
      renderWorkspaceDropdown();
    }
  }

  // --- Render Projects Sidebar ---
  function renderProjectsTree() {
    const treeContainer = document.getElementById("projectsTree");
    if (!treeContainer) return;
    treeContainer.innerHTML = "";
    const projects = Array.isArray(projectsList) ? projectsList : [];
    const conversations = Array.isArray(conversationsList) ? conversationsList : [];

    if (projects.length === 0) {
      treeContainer.innerHTML = `
        <div style="padding: 16px; color: var(--text-muted); font-size: 13px; line-height: 1.45;">
          ${canUseProtectedWorkspaceApis() ? "No workspaces found." : "Open http://localhost:8080 to load workspaces."}
        </div>
      `;
      return;
    }

    // Group conversations by project
    const convoByProject = {};
    conversations.forEach(c => {
      if (!convoByProject[c.project]) {
        convoByProject[c.project] = [];
      }
      convoByProject[c.project].push(c);
    });

    // Populate each project node
    projects.forEach(project => {
      const isAgy = project === "agy";
      const isVO = project === "VirtualOffice";
      const projectConversations = convoByProject[project] || [];

      const node = document.createElement("div");
      node.className = "project-node";

      // Folder Row
      const folderRow = document.createElement("div");
      folderRow.className = "project-folder-row";
      folderRow.setAttribute("data-project-name", project);

      folderRow.innerHTML = `
        <div class="project-folder-row-left">
          <svg viewBox="0 0 24 24" class="icon-chevron ${isAgy || isVO ? 'expanded' : ''}" id="chevron-${project}">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
          <svg viewBox="0 0 24 24" class="icon-folder">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <span>${project}</span>
        </div>
        <div class="project-folder-row-right">
          <!-- Add / Edit items -->
          <svg viewBox="0 0 24 24" width="10" height="10" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l-.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
          <svg viewBox="0 0 24 24" width="10" height="10" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
        </div>
      `;

      // Conversations Nested List
      const listContainer = document.createElement("div");
      listContainer.className = `project-convo-list ${isAgy || isVO ? '' : 'hidden'}`;
      listContainer.id = `list-${project}`;

      // Populate conversations for this project (limit to first 6 items)
      const displayedConvos = projectConversations.slice(0, 6);
      displayedConvos.forEach(c => {
        const item = document.createElement("div");
        const isActive = c.id === activeConversationId;
        const hasActiveDot = c.title.includes("Analyzing Risk") || c.title.includes("Debugging Production");

        item.className = `project-convo-item ${isActive ? 'active' : ''}`;
        item.setAttribute("data-convo-id", c.id);

        item.innerHTML = `
          <span class="project-convo-title" title="${c.title}">${c.title}</span>
          <div class="project-convo-meta">
            ${c.time && c.time !== "active" ? `<span class="time-badge">${c.time}</span>` : ""}
            ${hasActiveDot || isActive ? `<span class="active-dot"></span>` : ""}
          </div>
        `;

        item.addEventListener("click", (e) => {
          e.stopPropagation();
          loadConversation(c.id, project);
        });

        listContainer.appendChild(item);
      });

      // Append "See all (34)" specifically for VirtualOffice to match mockup
      if (project === "VirtualOffice" && projectConversations.length > 5) {
        const seeAll = document.createElement("div");
        seeAll.className = "project-convo-item see-all-link";
        seeAll.innerHTML = `<span style="color: var(--text-muted);">See all (34)</span>`;
        seeAll.addEventListener("click", (e) => {
          e.stopPropagation();
          showHistoryTab();
        });
        listContainer.appendChild(seeAll);
      }

      // Expansion Collapse Handler
      folderRow.addEventListener("click", () => {
        const chevron = folderRow.querySelector(".icon-chevron");
        listContainer.classList.toggle("hidden");
        chevron.classList.toggle("expanded");
      });

      node.appendChild(folderRow);
      node.appendChild(listContainer);
      treeContainer.appendChild(node);
    });

    // Handle project folder row chevrons css rotations
    const style = document.createElement('style');
    style.innerHTML = `
      .icon-chevron { transition: transform 0.2s ease; }
      .icon-chevron.expanded { transform: rotate(90deg); }
    `;
    document.head.appendChild(style);
  }

  // --- Render Top Picker Workspace list ---
  function renderWorkspaceDropdown() {
    if (!workspaceDropdown) return;
    workspaceDropdown.innerHTML = `<div class="dropdown-header">Workspaces</div>`;
    const projects = Array.isArray(projectsList) ? projectsList : [];
    if (projects.length === 0) {
      const item = document.createElement("div");
      item.className = "dropdown-item disabled";
      item.innerHTML = `<span>${canUseProtectedWorkspaceApis() ? "No workspaces found" : "Sign in to load workspaces"}</span>`;
      workspaceDropdown.appendChild(item);
      return;
    }
    projects.forEach(project => {
      const item = document.createElement("div");
      item.className = `dropdown-item ${project === currentWorkspace ? 'active' : ''}`;
      item.setAttribute("data-value", project);
      item.innerHTML = `
        <svg viewBox="0 0 24 24" class="icon-folder"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
        <span>${project}</span>
      `;
      workspaceDropdown.appendChild(item);
    });
  }

  // --- Load Conversation ---
  function loadConversation(cid, project) {
    if (!canUseProtectedWorkspaceApis()) {
      handleProtectedApiUnauthorized();
      return;
    }
    autoCloseMobileSidebar();
    activeConversationId = cid;
    currentWorkspace = project;
    if (headerProject) headerProject.textContent = project;

    const convoObj = conversationsList.find(c => c.id === cid);
    const convoTitle = convoObj ? convoObj.title : "Building Python Web App";
    if (headerConvo) headerConvo.textContent = convoTitle;

    // Highlights
    document.querySelectorAll(".project-convo-item").forEach(item => {
      const itemCid = item.getAttribute("data-convo-id");
      if (itemCid === cid) {
        item.classList.add("active");
      } else {
        item.classList.remove("active");
      }
    });

    // Switch view
    showChatTab();
    messagesContainer.innerHTML = "";
    welcomeScreen.classList.add("hidden");

    // Fetch messages
    fetch(`/api/conversation/${cid}`)
      .then(res => res.json())
      .then(data => {
        if (data.model) {
          if (data.effort) {
            if (["Light", "Medium", "High", "Extra High", "Ultra"].includes(data.effort)) {
              currentCodexEffort = data.effort;
            }
            if (["Low", "Medium", "High", "Extra", "Max"].includes(data.effort)) {
              currentClaudeEffort = data.effort;
            }
          }
          if (data.speed && ["Standard", "Fast"].includes(data.speed)) {
            currentCodexSpeed = data.speed;
          }
          if (data.thinking !== undefined) {
            currentClaudeThinking = data.thinking !== false;
          }
          applyModelSelection(data.model, false);
        } else if (data.provider === "agy" && currentProvider !== "agy") {
          applyModelSelection(defaultCatalogModel, false);
        }
        const messages = data.messages || [];
        if (messages.length === 0) {
          welcomeScreen.classList.remove("hidden");
        } else {
          messages.forEach((m, idx) => {
            const isLastMessage = (idx === messages.length - 1);
            appendMessage(m.role, m.content, !isLastMessage);
          });
        }
      })
      .catch(err => console.error("Error loading chat details:", err));
  }

  // --- Start New Conversation ---
  function startNewConversation() {
    autoCloseMobileSidebar();
    activeConversationId = generateUUID();
    messagesContainer.innerHTML = "";
    welcomeScreen.classList.remove("hidden");

    if (headerProject) headerProject.textContent = currentWorkspace;
    if (headerConvo) headerConvo.textContent = "New Conversation";

    // De-activate all selected sidebar conversation items
    document.querySelectorAll(".project-convo-item").forEach(el => el.classList.remove("active"));
    showChatTab();
  }
  newConvoBtn.addEventListener("click", startNewConversation);

  // --- Switch Tabs ---
  let activePanelId = "chatPanel";
  let panelSwitchTimer = null;

  function switchNavigationPanel(nextPanel) {
    const currentPanel = activePanelId === "historyPanel" ? historyPanel : chatPanel;
    if (currentPanel === nextPanel) return;

    if (panelSwitchTimer) {
      clearTimeout(panelSwitchTimer);
      panelSwitchTimer = null;
    }

    nextPanel.classList.remove("hidden", "panel-exiting");
    nextPanel.classList.add("panel-entering");

    currentPanel.classList.remove("panel-entering");
    currentPanel.classList.add("panel-exiting");

    panelSwitchTimer = setTimeout(() => {
      currentPanel.classList.add("hidden");
      currentPanel.classList.remove("panel-exiting");
      nextPanel.classList.remove("panel-entering");
      activePanelId = nextPanel.id;
    }, 260);
  }

  function showChatTab() {
    autoCloseMobileSidebar();
    switchNavigationPanel(chatPanel);
    historyMenuBtn.classList.remove("active");
  }

  function showHistoryTab() {
    autoCloseMobileSidebar();
    switchNavigationPanel(historyPanel);
    historyMenuBtn.classList.add("active");

    // Load History list content
    renderHistoryList();
  }
  historyMenuBtn.addEventListener("click", showHistoryTab);

  // --- Render Conversation History Panel (Screenshot 2) ---
  function renderHistoryList(filterQuery = "") {
    if (!canUseProtectedWorkspaceApis()) {
      historyList.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-muted);">Open http://localhost:8080 to load history.</div>`;
      handleProtectedApiUnauthorized();
      return;
    }
    historyList.innerHTML = "";

    fetch("/api/chat-history")
      .then(res => {
        if (res.status === 401) {
          handleProtectedApiUnauthorized();
          return { conversations: [] };
        }
        if (!res.ok) throw new Error(`Failed to load chat history (${res.status})`);
        return res.json();
      })
      .then(data => {
        const convos = data.conversations || [];

        // Filter elements
        const filtered = convos.filter(c =>
          c.title.toLowerCase().includes(filterQuery.toLowerCase()) ||
          c.project.toLowerCase().includes(filterQuery.toLowerCase())
        );

        if (filtered.length === 0) {
          historyList.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-muted);">No conversations found.</div>`;
          return;
        }

        filtered.forEach(c => {
          const item = document.createElement("div");
          const isActive = c.id === activeConversationId;
          const hasActiveDot = c.title.includes("Analyzing Risk") || c.title.includes("Debugging Production");

          item.className = "history-item";
          item.innerHTML = `
            <div class="history-item-left">
              <span class="history-item-title" title="${c.title}">${c.title}</span>
              <span class="history-item-project">${c.project}</span>
            </div>
            <div class="history-item-right">
              ${c.time && c.time !== "active" ? `<span>${c.time}</span>` : ""}
              ${hasActiveDot || isActive ? `<span class="active-dot"></span>` : ""}
            </div>
          `;

          item.addEventListener("click", () => {
            loadConversation(c.id, c.project);
          });

          historyList.appendChild(item);
        });
      })
      .catch(err => console.error("Error loading chat history:", err));
  }

  // Filter conversations list in history as user types
  historySearchInput.addEventListener("input", (e) => {
    renderHistoryList(e.target.value);
  });

  // --- Send Messages ---
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  function applyChatResponse(data, originalMessage) {
    if (data.status === "success") {
      appendMessage("assistant", data.reply);

      // CRITICAL: Update active session conversation ID if mapped/resolved by backend
      if (data.conversation_id && data.conversation_id !== activeConversationId) {
        activeConversationId = data.conversation_id;
        console.log("Session updated with resolved conversation ID:", activeConversationId);
        let displayTitle = originalMessage;
        if (displayTitle.length > 40) displayTitle = displayTitle.slice(0, 40) + "...";
        if (headerConvo) headerConvo.textContent = displayTitle;
      }

      // Refresh list on sidebar tree
      loadProjectsAndConversations();
    } else {
      appendMessage("assistant", data.reply || "⚠️ Error processing your prompt. Please try again.");
    }
  }

  async function sendDirectMessage(message) {
    if (!canUseProtectedWorkspaceApis()) {
      handleProtectedApiUnauthorized();
      appendMessage("assistant", "⚠️ Please sign in with Google before sending messages from the Cloudflare URL.");
      return;
    }
    if (!welcomeScreen.classList.contains("hidden")) {
      welcomeScreen.classList.add("hidden");
    }

    appendMessage("user", message);
    const typingIndicator = appendTypingIndicator();
    const progressEvents = [];
    let lastSeq = -1;

    try {
      const startResponse = await fetch("/api/chat-tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          message: message,
          model: currentModel,
          provider: currentProvider,
          effort: ["claude", "xai", "muse"].includes(currentProvider) ? currentClaudeEffort : currentCodexEffort,
          speed: currentCodexSpeed,
          thinking: currentClaudeThinking,
          workspace: currentWorkspace,
          target: currentTarget,
          conversation_id: activeConversationId
        })
      });
      const startData = await startResponse.json();
      if (!startResponse.ok || !startData.task_id) {
        throw new Error(startData.detail || "Failed to start chat task");
      }

      while (true) {
        await wait(1500);
        const pollResponse = await fetch(`/api/chat-tasks/${startData.task_id}?after=${lastSeq}`);
        const taskData = await pollResponse.json();
        if (!pollResponse.ok) {
          throw new Error(taskData.detail || "Failed to poll chat task");
        }

        if (Array.isArray(taskData.events) && taskData.events.length) {
          taskData.events.forEach(event => {
            progressEvents.push(event);
            lastSeq = Math.max(lastSeq, event.seq);
          });
          updateTypingProgress(typingIndicator, progressEvents);
        }

        if (taskData.status === "success" || taskData.status === "error") {
          typingIndicator.remove();
          applyChatResponse(taskData.result || { status: "error" }, message);
          break;
        }
      }
    } catch (err) {
      console.error("Chat task error:", err);
      typingIndicator.remove();
      appendMessage("assistant", "⚠️ Network or server error. Please try again.");
    }
  }

  function sendMessage() {
    const message = promptTextarea.value.trim();
    if (!message) return;

    promptTextarea.value = "";
    adjustTextareaHeight();
    autocompletePopup.classList.add("hidden");
    isSuggesting = false;

    sendDirectMessage(message);
  }

  sendBtn.addEventListener("click", sendMessage);

  // --- Web Speech API microphone handler ---
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "th-TH";

    recognition.onstart = () => {
      isRecording = true;
      micBtn.classList.add("recording");
    };

    recognition.onend = () => {
      isRecording = false;
      micBtn.classList.remove("recording");
    };

    recognition.onresult = (event) => {
      const speechToText = event.results[0][0].transcript;
      const start = promptTextarea.selectionStart;
      const end = promptTextarea.selectionEnd;
      const currentVal = promptTextarea.value;
      promptTextarea.value = currentVal.substring(0, start) + speechToText + currentVal.substring(end);
      promptTextarea.focus();
      adjustTextareaHeight();
    };

    recognition.onerror = (event) => {
      console.error("Speech Recognition Error:", event.error);
      isRecording = false;
      micBtn.classList.remove("recording");
    };
  } else {
    micBtn.setAttribute("title", "Voice typing not supported on this browser");
    micBtn.style.opacity = "0.5";
  }

  micBtn.addEventListener("click", () => {
    if (!recognition) return;
    if (isRecording) {
      recognition.stop();
    } else {
      recognition.start();
    }
  });

  // --- Auto-resize Textarea ---
  function adjustTextareaHeight() {
    promptTextarea.style.height = "auto";
    promptTextarea.style.height = Math.min(promptTextarea.scrollHeight, 200) + "px";
  }
  promptTextarea.addEventListener("input", adjustTextareaHeight);

  // --- Autocomplete Tags & Commands System ---
  const slashCommands = [
    { name: "/watch", desc: "Watch & analyze video (URL or local path)", type: "Command" },
    { name: "/goal", desc: "Initiate goal mode checklist", type: "Command" },
    { name: "/browser", desc: "Launch browser automation tool", type: "Command" },
    { name: "/grill-me", desc: "Launch requirements audit survey", type: "Command" },
    { name: "/grill-with-docs", desc: "Doc-driven architecture alignment", type: "Command" },
    { name: "/help", desc: "Show prompt help context panel", type: "Command" }
  ];

  function showAutocomplete() {
    autocompletePopup.innerHTML = "";
    if (suggestionList.length === 0) {
      autocompletePopup.classList.add("hidden");
      isSuggesting = false;
      return;
    }

    suggestionList.forEach((item, idx) => {
      const div = document.createElement("div");
      div.className = `autocomplete-item ${idx === suggestionIndex ? "selected" : ""}`;

      let leftSymbol = item.name.charAt(0);
      let nameText = item.name;
      let descText = item.desc;
      let rightText = item.type;

      div.innerHTML = `
        <div class="autocomplete-item-left">
          <span class="autocomplete-symbol">${leftSymbol}</span>
          <span class="autocomplete-text">${nameText.slice(1)}</span>
          <span class="autocomplete-desc">— ${descText}</span>
        </div>
        <div class="autocomplete-item-right">${rightText}</div>
      `;

      div.addEventListener("click", () => {
        selectAutocompleteItem(item);
      });

      autocompletePopup.appendChild(div);
    });

    autocompletePopup.classList.remove("hidden");
    isSuggesting = true;
  }

  function selectAutocompleteItem(item) {
    const text = promptTextarea.value;
    const cursor = promptTextarea.selectionStart;
    const textBeforeCursor = text.substring(0, cursor);
    const triggerIndex = textBeforeCursor.lastIndexOf(suggestionType);

    if (triggerIndex !== -1) {
      const textAfterCursor = text.substring(cursor);
      promptTextarea.value = textBeforeCursor.substring(0, triggerIndex) + item.name + " " + textAfterCursor;
      promptTextarea.focus();

      const newCursorPos = triggerIndex + item.name.length + 1;
      promptTextarea.setSelectionRange(newCursorPos, newCursorPos);
    }

    autocompletePopup.classList.add("hidden");
    isSuggesting = false;
    adjustTextareaHeight();
  }

  function filterSuggestions() {
    const text = promptTextarea.value;
    const cursor = promptTextarea.selectionStart;
    const textBeforeCursor = text.substring(0, cursor);
    const lastWord = textBeforeCursor.split(/\s+/).pop();

    if (lastWord.startsWith("/")) {
      suggestionType = "/";
      suggestionQuery = lastWord;
      suggestionList = slashCommands.filter(c => c.name.startsWith(suggestionQuery));
      suggestionIndex = Math.min(suggestionIndex, suggestionList.length - 1);
      if (suggestionIndex < 0) suggestionIndex = 0;
      showAutocomplete();
    } else if (lastWord.startsWith("@")) {
      suggestionType = "@";
      suggestionQuery = lastWord;
      suggestionList = workspaceFiles
        .map(f => ({ name: "@" + f.name, desc: f.type + " (" + f.size + ")", type: "File" }))
        .filter(f => f.name.toLowerCase().includes(suggestionQuery.toLowerCase()));
      suggestionIndex = Math.min(suggestionIndex, suggestionList.length - 1);
      if (suggestionIndex < 0) suggestionIndex = 0;
      showAutocomplete();
    } else {
      autocompletePopup.classList.add("hidden");
      isSuggesting = false;
    }
  }

  promptTextarea.addEventListener("keydown", (e) => {
    if (isSuggesting) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        suggestionIndex = (suggestionIndex + 1) % suggestionList.length;
        showAutocomplete();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        suggestionIndex = (suggestionIndex - 1 + suggestionList.length) % suggestionList.length;
        showAutocomplete();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (suggestionList[suggestionIndex]) {
          selectAutocompleteItem(suggestionList[suggestionIndex]);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        autocompletePopup.classList.add("hidden");
        isSuggesting = false;
      }
    } else {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    }
  });

  promptTextarea.addEventListener("input", filterSuggestions);
  promptTextarea.addEventListener("keyup", (e) => {
    if (e.key === "Backspace" || e.key === "Delete") {
      filterSuggestions();
    }
  });

  // --- Rendering Helpers ---
  function appendMessage(role, content, isDisabled = false) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    let questionPayload = null;
    if (role === "assistant") {
      try {
        let clean = content.trim();
        const jsonMatch = clean.match(/(\{[\s\S]*?"type"\s*:\s*"question"[\s\S]*?\})/);
        if (jsonMatch) {
          clean = jsonMatch[1].trim();
        } else {
          if (clean.startsWith('```json')) clean = clean.slice(7);
          if (clean.startsWith('```')) clean = clean.slice(3);
          if (clean.endsWith('```')) clean = clean.slice(0, -3);
          clean = clean.trim();
        }
        const parsed = JSON.parse(clean);
        if (parsed && parsed.type === "question" && typeof parsed.question === "string" && Array.isArray(parsed.options)) {
          questionPayload = parsed;
        }
      } catch(e) {}
    }

    if (questionPayload) {
      renderQuestionCard(bubble, questionPayload, isDisabled);
    } else {
      bubble.innerHTML = window.marked ? window.marked.parse(content) : content;
    }

    if (role !== "user") {
      const avatar = document.createElement("div");
      avatar.className = `avatar ${role}`;
      avatar.textContent = "G";
      row.appendChild(avatar);
    }

    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function renderQuestionCard(container, qObj, isDisabled = false) {
    const card = document.createElement("div");
    card.className = "question-card-container" + (isDisabled ? " disabled" : "");

    const title = document.createElement("div");
    title.className = "question-title-text";
    title.textContent = qObj.question;
    card.appendChild(title);

    let selectedOptionText = "";

    qObj.options.forEach((opt, idx) => {
      const row = document.createElement("div");
      row.className = "question-option-row";
      row.innerHTML = `
        <div class="question-option-num">${idx + 1}</div>
        <div class="question-option-text">${opt}</div>
      `;
      row.addEventListener("click", () => {
        if (isDisabled || card.classList.contains("disabled")) return;
        card.querySelectorAll(".question-option-row").forEach(r => r.classList.remove("selected"));
        row.classList.add("selected");
        selectedOptionText = opt;
      });
      card.appendChild(row);
    });

    if (qObj.allow_other) {
      const otherRow = document.createElement("div");
      otherRow.className = "question-option-row";
      otherRow.innerHTML = `
        <div class="question-option-num">${qObj.options.length + 1}</div>
        <div class="question-option-text" style="display: flex; align-items: center; gap: 8px; flex-grow: 1;">
          <span style="flex-shrink:0;">Other:</span>
          <input type="text" class="question-other-input" placeholder="Write your answer..." />
        </div>
      `;
      const input = otherRow.querySelector(".question-other-input");
      if (isDisabled) {
        input.disabled = true;
      }
      input.addEventListener("click", (e) => e.stopPropagation());
      input.addEventListener("input", () => {
        selectedOptionText = input.value;
      });
      otherRow.addEventListener("click", () => {
        if (isDisabled || card.classList.contains("disabled")) return;
        card.querySelectorAll(".question-option-row").forEach(r => r.classList.remove("selected"));
        otherRow.classList.add("selected");
        selectedOptionText = input.value;
        input.focus();
      });
      card.appendChild(otherRow);
    }

    if (!isDisabled) {
      const actions = document.createElement("div");
      actions.className = "question-actions-row";

      const skipBtn = document.createElement("button");
      skipBtn.className = "question-skip-btn";
      skipBtn.textContent = "Skip";
      skipBtn.addEventListener("click", () => {
        if (card.classList.contains("disabled")) return;
        card.classList.add("disabled");
        sendDirectMessage("Skip");
      });

      const submitBtn = document.createElement("button");
      submitBtn.className = "question-submit-btn";
      submitBtn.textContent = "Submit \u21B5";
      submitBtn.addEventListener("click", () => {
        if (card.classList.contains("disabled")) return;
        if (!selectedOptionText.trim()) {
          alert("Please select an option or write an answer!");
          return;
        }
        card.classList.add("disabled");
        sendDirectMessage(selectedOptionText);
      });

      actions.appendChild(skipBtn);
      actions.appendChild(submitBtn);
      card.appendChild(actions);
    }

    container.appendChild(card);
  }

  function appendTypingIndicator() {
    const row = document.createElement("div");
    row.className = "message-row assistant typing-row";

    const avatar = document.createElement("div");
    avatar.className = "avatar assistant";
    avatar.textContent = "G";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = `
      <div class="typing-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
    `;

    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    chatScroll.scrollTop = chatScroll.scrollHeight;

    return row;
  }

  function updateTypingProgress(row, events) {
    if (!row || !events.length) return;
    const bubble = row.querySelector(".message-bubble");
    if (!bubble) return;

    const lines = events.slice(-8).map(event => {
      const marker = event.type === "error" ? "Error" : "Progress";
      return `- **${marker}:** ${event.message}`;
    }).join("\n");

    const content = `**Running task...**\n\n${lines}`;
    bubble.innerHTML = window.marked ? window.marked.parse(content) : content;
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  // --- Dropdown Layout Helpers ---
  function positionDropdown(btn, dropdown, direction = "down") {
    dropdown.classList.remove("hidden");
    if (window.innerWidth <= 600) {
      dropdown.style.top = "";
      dropdown.style.left = "";
      dropdown.style.bottom = "";
      return;
    }
    const rect = btn.getBoundingClientRect();
    const dropdownWidth = dropdown.offsetWidth || 260;
    let left = rect.left;
    if (left + dropdownWidth > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - dropdownWidth - 12);
    }
    if (direction === "up") {
      dropdown.style.top = "";
      dropdown.style.bottom = `${window.innerHeight - rect.top + 8}px`;
      dropdown.style.left = `${left}px`;
    } else {
      dropdown.style.bottom = "";
      dropdown.style.top = `${rect.bottom + 8}px`;
      dropdown.style.left = `${left}px`;
    }
  }

  window.addEventListener("click", (e) => {
    if (workspaceDropdown && !workspaceDropdown.contains(e.target) && (!projectPickerBtn || !projectPickerBtn.contains(e.target))) {
      workspaceDropdown.classList.add("hidden");
    }
    if (!modelBtn.contains(e.target) && !modelDropdown.contains(e.target)) {
      modelDropdown.classList.add("hidden");
    }
    if (codexEffortBtn && !codexEffortBtn.contains(e.target) && !codexEffortDropdown.contains(e.target) && !claudeEffortDropdown?.contains(e.target)) {
      codexEffortDropdown.classList.add("hidden");
      claudeEffortDropdown?.classList.add("hidden");
    }
    if (codexSpeedBtn && !codexSpeedBtn.contains(e.target) && !codexSpeedDropdown.contains(e.target)) {
      codexSpeedDropdown.classList.add("hidden");
    }
    if (!targetBtn.contains(e.target) && !targetDropdown.contains(e.target)) {
      targetDropdown.classList.add("hidden");
    }
    const plusMenu = document.getElementById("plusMenu");
    if (plusMenu && !plusBtn.contains(e.target) && !plusMenu.contains(e.target)) {
      plusMenu.classList.add("hidden");
    }
  });

  if (projectPickerBtn) {
    projectPickerBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      modelDropdown.classList.add("hidden");
      targetDropdown.classList.add("hidden");
      if (workspaceDropdown.classList.contains("hidden")) {
        positionDropdown(projectPickerBtn, workspaceDropdown, "down");
      } else {
        workspaceDropdown.classList.add("hidden");
      }
    });
  }

  modelBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    workspaceDropdown.classList.add("hidden");
    targetDropdown.classList.add("hidden");
    codexEffortDropdown.classList.add("hidden");
    claudeEffortDropdown?.classList.add("hidden");
    codexSpeedDropdown.classList.add("hidden");
    if (modelDropdown.classList.contains("hidden")) {
      positionDropdown(modelBtn, modelDropdown, "up");
    } else {
      modelDropdown.classList.add("hidden");
    }
  });

  codexEffortBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    modelDropdown.classList.add("hidden");
    codexSpeedDropdown.classList.add("hidden");
    const effortDropdown = ["claude", "xai", "muse"].includes(currentProvider)
      ? claudeEffortDropdown
      : codexEffortDropdown;
    if (effortDropdown?.classList.contains("hidden")) {
      positionDropdown(codexEffortBtn, effortDropdown, "up");
    } else {
      effortDropdown?.classList.add("hidden");
    }
  });

  codexSpeedBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    if (["claude", "xai", "muse"].includes(currentProvider)) {
      const reasoningCapability = CLAUDE_MODELS[currentModel] || XAI_MODELS[currentModel] || MUSE_MODELS[currentModel];
      if (!reasoningCapability?.thinkingRequired) {
        currentClaudeThinking = !currentClaudeThinking;
        updateCodexControls();
        saveAppPreferences();
      }
      return;
    }
    modelDropdown.classList.add("hidden");
    codexEffortDropdown.classList.add("hidden");
    if (codexSpeedDropdown.classList.contains("hidden")) {
      positionDropdown(codexSpeedBtn, codexSpeedDropdown, "up");
    } else {
      codexSpeedDropdown.classList.add("hidden");
    }
  });

  targetBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    workspaceDropdown.classList.add("hidden");
    modelDropdown.classList.add("hidden");
    if (targetDropdown.classList.contains("hidden")) {
      positionDropdown(targetBtn, targetDropdown, "up");
    } else {
      targetDropdown.classList.add("hidden");
    }
  });

  workspaceDropdown.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item) return;
    workspaceDropdown.querySelectorAll(".dropdown-item").forEach(el => el.classList.remove("active"));
    item.classList.add("active");
    const val = item.getAttribute("data-value");
    currentWorkspace = val;
    if (headerProject) headerProject.textContent = val;
    workspaceDropdown.classList.add("hidden");
    startNewConversation();
  });

  modelDropdown.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item) return;
    modelDropdown.querySelectorAll(".dropdown-item").forEach(el => el.classList.remove("active"));
    item.classList.add("active");
    const val = item.getAttribute("data-value");
    applyModelSelection(val);
    modelDropdown.classList.add("hidden");
    saveAppPreferences();
    refreshUsageDisplay();
  });

  codexEffortDropdown.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item || item.classList.contains("hidden")) return;
    currentCodexEffort = item.getAttribute("data-value");
    updateCodexControls();
    codexEffortDropdown.classList.add("hidden");
    saveAppPreferences();
  });

  claudeEffortDropdown?.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item || item.classList.contains("hidden")) return;
    currentClaudeEffort = item.getAttribute("data-value");
    updateCodexControls();
    claudeEffortDropdown.classList.add("hidden");
    saveAppPreferences();
  });

  codexSpeedDropdown.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item || item.classList.contains("hidden")) return;
    currentCodexSpeed = item.getAttribute("data-value");
    updateCodexControls();
    codexSpeedDropdown.classList.add("hidden");
    saveAppPreferences();
  });

  targetDropdown.addEventListener("click", (e) => {
    const item = e.target.closest(".dropdown-item");
    if (!item) return;
    targetDropdown.querySelectorAll(".dropdown-item").forEach(el => el.classList.remove("active"));
    item.classList.add("active");
    const val = item.getAttribute("data-value");
    currentTarget = val;
    currentTargetText.textContent = val;
    targetDropdown.classList.add("hidden");
    saveAppPreferences();
  });

  const plusMenu = document.getElementById("plusMenu");
  const mediaFileInput = document.getElementById("mediaFileInput");
  const plusItemMedia = document.getElementById("plusItemMedia");
  const plusItemMentions = document.getElementById("plusItemMentions");
  const plusItemActions = document.getElementById("plusItemActions");
  const plusItemBrowser = document.getElementById("plusItemBrowser");

  plusBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    plusMenu.classList.toggle("hidden");
  });

  plusItemMedia.addEventListener("click", () => {
    mediaFileInput.click();
    plusMenu.classList.add("hidden");
  });

  mediaFileInput.addEventListener("change", async () => {
    if (mediaFileInput.files.length === 0) return;
    if (!canUseProtectedWorkspaceApis()) {
      handleProtectedApiUnauthorized();
      alert("Media upload from the web client is localhost-only. Open http://localhost:8080.");
      mediaFileInput.value = "";
      return;
    }
    const file = mediaFileInput.files[0];

    try {
      const response = await fetch(`/api/upload-media?conversation_id=${activeConversationId}&filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream"
        },
        body: file
      });
      const res = await response.json();
      if (response.status === 401) {
        handleProtectedApiUnauthorized();
        alert("Media upload from the web client is localhost-only. Open http://localhost:8080.");
        return;
      }
      if (res.status === "success") {
        // Successfully uploaded! Reload conversation details to show the attachment
        loadConversation(activeConversationId, currentWorkspace);
      } else {
        alert("Upload failed: " + res.detail);
      }
    } catch (err) {
      console.error("Upload error:", err);
      alert("Error uploading image: " + err.message);
    }
    mediaFileInput.value = ""; // reset picker
  });

  plusItemMentions.addEventListener("click", () => {
    plusMenu.classList.add("hidden");
    const cursor = promptTextarea.selectionStart;
    const text = promptTextarea.value;
    promptTextarea.value = text.substring(0, cursor) + "@" + text.substring(cursor);
    promptTextarea.selectionStart = promptTextarea.selectionEnd = cursor + 1;
    promptTextarea.focus();
    adjustTextareaHeight();
    filterSuggestions();
  });

  plusItemActions.addEventListener("click", () => {
    plusMenu.classList.add("hidden");
    const cursor = promptTextarea.selectionStart;
    const text = promptTextarea.value;
    promptTextarea.value = text.substring(0, cursor) + "/" + text.substring(cursor);
    promptTextarea.selectionStart = promptTextarea.selectionEnd = cursor + 1;
    promptTextarea.focus();
    adjustTextareaHeight();
    filterSuggestions();
  });

  plusItemBrowser.addEventListener("click", () => {
    plusMenu.classList.add("hidden");
    const cursor = promptTextarea.selectionStart;
    const text = promptTextarea.value;
    promptTextarea.value = text.substring(0, cursor) + "/browser " + text.substring(cursor);
    promptTextarea.selectionStart = promptTextarea.selectionEnd = cursor + 9;
    promptTextarea.focus();
    adjustTextareaHeight();
    filterSuggestions();
  });

  // --- Settings Modal Logic ---
  const settingsBtn = document.getElementById("settingsBtn");
  const settingsModal = document.getElementById("settingsModal");
  const settingsCloseBtn = document.getElementById("settingsCloseBtn");
  const settingsSaveBtn = document.getElementById("settingsSaveBtn");
  const settingsDefaultModel = document.getElementById("settingsDefaultModel");
  const settingsCodexEffort = document.getElementById("settingsCodexEffort");
  const settingsCodexSpeed = document.getElementById("settingsCodexSpeed");
  const settingsClaudeEffort = document.getElementById("settingsClaudeEffort");
  const settingsClaudeThinking = document.getElementById("settingsClaudeThinking");
  const settingsDefaultTarget = document.getElementById("settingsDefaultTarget");
  const settingsSpeechLang = document.getElementById("settingsSpeechLang");
  const settingsThemeMode = document.getElementById("settingsThemeMode");
  const modelCatalogEditor = document.getElementById("modelCatalogEditor");
  const modelCatalogSummary = document.getElementById("modelCatalogSummary");
  const modelCatalogMessage = document.getElementById("modelCatalogMessage");
  const modelCatalogRefreshBtn = document.getElementById("modelCatalogRefreshBtn");
  const modelCatalogSaveBtn = document.getElementById("modelCatalogSaveBtn");
  const cliConnectionsList = document.getElementById("cliConnectionsList");
  const cliRequirementsSummary = document.getElementById("cliRequirementsSummary");
  const cliRefreshBtn = document.getElementById("cliRefreshBtn");
  const CLI_STATUS_TIMEOUT_MS = 15000;
  let cliStatusLoading = false;

  function setModelCatalogMessage(message, isError = false) {
    if (!modelCatalogMessage) return;
    modelCatalogMessage.textContent = message;
    modelCatalogMessage.classList.toggle("error", isError);
  }

  async function loadModelCatalogEditor() {
    if (!modelCatalogEditor || !canUseProtectedWorkspaceApis()) return;
    if (modelCatalogRefreshBtn) modelCatalogRefreshBtn.disabled = true;
    setModelCatalogMessage("Loading…");
    try {
      const response = await fetch("/api/models?include_disabled=true");
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to load model catalog");
      }
      modelCatalogEditor.value = JSON.stringify(data, null, 2);
      if (modelCatalogSummary) {
        modelCatalogSummary.textContent =
          `Version ${data.catalog_version} · ${data.models.length} configured models`;
      }
      setModelCatalogMessage("");
    } catch (error) {
      setModelCatalogMessage(error.message || "Failed to load model catalog", true);
    } finally {
      if (modelCatalogRefreshBtn) modelCatalogRefreshBtn.disabled = false;
    }
  }

  async function saveModelCatalogEditor() {
    if (!modelCatalogEditor || !modelCatalogSaveBtn) return;
    let payload;
    try {
      payload = JSON.parse(modelCatalogEditor.value);
    } catch (error) {
      setModelCatalogMessage(`Invalid JSON: ${error.message}`, true);
      return;
    }

    modelCatalogSaveBtn.disabled = true;
    setModelCatalogMessage("Validating and saving…");
    try {
      const response = await fetch("/api/models", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to save model catalog");
      }
      renderModelCatalog(data);
      modelCatalogEditor.value = JSON.stringify({
        schema_version: data.schema_version,
        catalog_version: data.catalog_version,
        default_model: data.default_model,
        models: data.models
      }, null, 2);
      if (modelCatalogSummary) {
        modelCatalogSummary.textContent =
          `Version ${data.catalog_version} · ${data.models.length} configured models`;
      }
      setModelCatalogMessage("Saved. Web and mobile clients will refresh automatically.");
    } catch (error) {
      setModelCatalogMessage(error.message || "Failed to save model catalog", true);
    } finally {
      modelCatalogSaveBtn.disabled = false;
    }
  }

  modelCatalogRefreshBtn?.addEventListener("click", loadModelCatalogEditor);
  modelCatalogSaveBtn?.addEventListener("click", saveModelCatalogEditor);

  const CLI_ICON_LABELS = {
    agy: "AG",
    kimi: "KI",
    grok: "GX",
    muse: "MU",
    claude: "CL",
    codex: "CX"
  };

  function renderCliStatuses(payload) {
    if (!cliConnectionsList) return;
    const clis = Array.isArray(payload?.clis) ? payload.clis : [];
    const canManage = payload?.can_manage === true;
    const installedCount = clis.filter(cli => cli.installed).length;

    if (cliRequirementsSummary) {
      const accessNote = canManage ? "" : " · Admin access required to manage";
      cliRequirementsSummary.textContent =
        `${installedCount} of ${clis.length} required tools installed${accessNote}`;
    }

    if (!clis.length) {
      cliConnectionsList.innerHTML =
        '<div class="cli-empty">No CLI requirements were found in requirements.txt.</div>';
      return;
    }

    cliConnectionsList.innerHTML = clis.map(cli => {
      const status = ["installed", "installing", "error"].includes(cli.status)
        ? cli.status
        : (cli.installed ? "installed" : "missing");
      const statusLabel = {
        installed: "Installed",
        installing: "Installing",
        error: "Install failed",
        missing: "Missing"
      }[status];
      const detail = cli.message || cli.version || cli.connect_help || "";
      const detailClass = status === "error" ? " error" : "";
      const installLabel = status === "error" ? "Retry install" : "Install";
      const disableInstall = !canManage || status === "installing";
      const disableConnect = !canManage || !cli.installed || status === "installing";

      return `
        <div class="cli-connection-card" data-cli-card="${escapeHtml(cli.id)}">
          <div class="cli-provider-icon">${escapeHtml(CLI_ICON_LABELS[cli.id] || cli.id.slice(0, 2).toUpperCase())}</div>
          <div class="cli-provider-info">
            <div class="cli-provider-title-row">
              <span class="cli-provider-name">${escapeHtml(cli.name)}</span>
              <span class="cli-status-pill ${status}">${statusLabel}</span>
            </div>
            <div class="cli-provider-detail${detailClass}">${escapeHtml(detail)}</div>
          </div>
          <div class="cli-actions">
            <button
              type="button"
              class="cli-action-btn"
              data-cli-action="install"
              data-cli-id="${escapeHtml(cli.id)}"
              ${cli.installed ? "hidden" : ""}
              ${disableInstall ? "disabled" : ""}
            >${installLabel}</button>
            <button
              type="button"
              class="cli-action-btn primary"
              data-cli-action="connect"
              data-cli-id="${escapeHtml(cli.id)}"
              ${disableConnect ? "disabled" : ""}
            >Connect</button>
          </div>
          <div class="cli-action-message hidden" data-cli-message></div>
        </div>
      `;
    }).join("");
  }

  function renderCliStatusError(message) {
    if (cliRequirementsSummary) {
      cliRequirementsSummary.textContent = "Could not load CLI requirements";
    }
    if (cliConnectionsList) {
      cliConnectionsList.innerHTML =
        `<div class="cli-empty">${escapeHtml(message)}</div>`;
    }
  }

  async function loadCliStatuses() {
    if (cliStatusLoading) return;
    cliStatusLoading = true;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CLI_STATUS_TIMEOUT_MS);
    if (cliRefreshBtn) {
      cliRefreshBtn.disabled = true;
      cliRefreshBtn.textContent = "Checking…";
    }
    try {
      const response = await fetch("/api/cli/status", {
        signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to load CLI status");
      }
      renderCliStatuses(data);
    } catch (error) {
      const message = error?.name === "AbortError"
        ? "CLI status check timed out. Click Refresh to try again."
        : (error.message || "Failed to load CLI status");
      renderCliStatusError(message);
    } finally {
      clearTimeout(timeoutId);
      cliStatusLoading = false;
      if (cliRefreshBtn) {
        cliRefreshBtn.disabled = false;
        cliRefreshBtn.textContent = "Refresh";
      }
    }
  }

  function setCliActionMessage(cliId, message, isError = false) {
    const card = cliConnectionsList?.querySelector(
      `[data-cli-card="${CSS.escape(cliId)}"]`
    );
    const messageElement = card?.querySelector("[data-cli-message]");
    if (!messageElement) return;
    messageElement.textContent = message;
    messageElement.classList.toggle("error", isError);
    messageElement.classList.toggle("hidden", !message);
  }

  async function runCliAction(cliId, action) {
    const card = cliConnectionsList?.querySelector(
      `[data-cli-card="${CSS.escape(cliId)}"]`
    );
    const buttons = card?.querySelectorAll(".cli-action-btn") || [];
    buttons.forEach(button => { button.disabled = true; });
    setCliActionMessage(
      cliId,
      action === "install"
        ? "Downloading and installing this CLI…"
        : "Opening the sign-in flow on the server computer…"
    );

    try {
      const response = await fetch(`/api/cli/${encodeURIComponent(cliId)}/${action}`, {
        method: "POST"
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = data.detail || data.message || data.cli?.message || "CLI action failed";
        const manualCommand = data.command ? ` Run manually: ${data.command}` : "";
        throw new Error(detail + manualCommand);
      }
      if (action === "connect") {
        setCliActionMessage(cliId, data.message || "Sign-in terminal opened.");
        buttons.forEach(button => {
          if (button.dataset.cliAction === "connect") button.disabled = false;
        });
      } else {
        await loadCliStatuses();
      }
    } catch (error) {
      setCliActionMessage(cliId, error.message || "CLI action failed", true);
      buttons.forEach(button => { button.disabled = false; });
    }
  }

  if (cliRefreshBtn) {
    cliRefreshBtn.addEventListener("click", loadCliStatuses);
  }

  if (cliConnectionsList) {
    cliConnectionsList.addEventListener("click", event => {
      const button = event.target.closest("[data-cli-action]");
      if (!button || button.disabled) return;
      runCliAction(button.dataset.cliId, button.dataset.cliAction);
    });
  }

  const DEFAULT_SETTINGS_TAB = "settingsGeneral";

  function activateSettingsTab(targetId = DEFAULT_SETTINGS_TAB) {
    const settingsTabs = settingsModal.querySelector(".settings-tabs");
    const targetTab = settingsModal.querySelector(
      `.settings-tab[data-target="${CSS.escape(targetId)}"]`
    );
    const targetContent = document.getElementById(targetId);
    if (!targetTab || !targetContent) return;

    settingsModal.querySelectorAll(".settings-tab").forEach(tab => {
      tab.classList.toggle("active", tab === targetTab);
    });
    settingsModal.querySelectorAll(".settings-tab-content").forEach(content => {
      content.classList.toggle("hidden", content !== targetContent);
    });
    targetContent.scrollTop = 0;
    if (targetId === DEFAULT_SETTINGS_TAB && settingsTabs) {
      settingsTabs.scrollLeft = 0;
    }

    if (targetId === "settingsCli") {
      loadCliStatuses();
    } else if (targetId === "settingsModels") {
      loadModelCatalogEditor();
    }
  }

  const settingsWhisperKey = document.getElementById("settingsWhisperKey");
  const settingsWhisperHint = document.getElementById("settingsWhisperHint");

  async function loadServerSettings() {
    if (!settingsWhisperKey) return;
    try {
      const res = await fetch("/api/settings");
      if (res.ok) {
        const data = await res.json();
        if (data.has_groq_key) {
          settingsWhisperKey.placeholder = `${data.groq_api_key_masked} (${data.groq_key_count} active keys)`;
          if (settingsWhisperHint) {
            settingsWhisperHint.textContent = `Currently active (${data.groq_key_count} key(s)): ${data.groq_api_key_masked}. Enter new key(s) to add/update.`;
          }
        } else {
          settingsWhisperKey.placeholder = "gsk_key1, gsk_key2 (Multiple keys supported)";
          if (settingsWhisperHint) {
            settingsWhisperHint.textContent = "No Whisper key configured. Get a free key at console.groq.com/keys";
          }
        }
      }
    } catch (err) {
      console.warn("Failed to load server settings:", err);
    }
  }

  settingsBtn.addEventListener("click", () => {
    // Populate with current configurations
    settingsDefaultModel.value = currentModel;
    settingsCodexEffort.value = currentCodexEffort;
    settingsCodexSpeed.value = currentCodexSpeed;
    settingsClaudeEffort.value = currentClaudeEffort;
    settingsClaudeThinking.value = currentClaudeThinking ? "On" : "Off";
    updateCodexControls();
    settingsDefaultTarget.value = currentTarget;
    setThemeModeControl(currentThemeMode);
    if (recognition) {
      settingsSpeechLang.value = recognition.lang || "th-TH";
    }
    loadServerSettings();
    activateSettingsTab();
    settingsModal.classList.remove("hidden");
  });

  settingsDefaultModel.addEventListener("change", () => {
    const capability = CODEX_MODELS[settingsDefaultModel.value];
    const claudeCapability = CLAUDE_MODELS[settingsDefaultModel.value];
    const xaiCapability = XAI_MODELS[settingsDefaultModel.value];
    const museCapability = MUSE_MODELS[settingsDefaultModel.value];
    const reasoningCapability = claudeCapability || xaiCapability || museCapability;
    const effortGroupLabel = document.querySelector(
      "#settingsClaudeEffortGroup label"
    );
    const thinkingGroupLabel = document.querySelector(
      "#settingsClaudeThinkingGroup label"
    );
    if (effortGroupLabel) {
      effortGroupLabel.textContent = museCapability
        ? "Muse Reasoning Effort"
        : (xaiCapability ? "Grok Reasoning Effort" : "Claude Effort");
    }
    if (thinkingGroupLabel) {
      thinkingGroupLabel.textContent = museCapability
        ? "Muse Reasoning"
        : (xaiCapability ? "Grok Reasoning" : "Claude Thinking");
    }
    document.getElementById("settingsCodexEffortGroup")?.classList.toggle("hidden", !capability);
    document.getElementById("settingsCodexSpeedGroup")?.classList.toggle("hidden", !capability);
    document.getElementById("settingsClaudeEffortGroup")?.classList.toggle("hidden", !reasoningCapability?.effort);
    document.getElementById("settingsClaudeThinkingGroup")?.classList.toggle("hidden", !reasoningCapability);
    const ultraOption = settingsCodexEffort.querySelector('option[value="Ultra"]');
    const fastOption = settingsCodexSpeed.querySelector('option[value="Fast"]');
    ultraOption.disabled = !capability?.ultra;
    fastOption.disabled = !capability?.fast;
    if (!capability?.ultra && settingsCodexEffort.value === "Ultra") {
      settingsCodexEffort.value = "Medium";
    }
    if (!capability?.fast && settingsCodexSpeed.value === "Fast") {
      settingsCodexSpeed.value = "Standard";
    }
    const settingsEfforts = xaiCapability?.efforts || museCapability?.efforts;
    settingsClaudeEffort.querySelectorAll("option").forEach(option => {
      option.disabled = settingsEfforts?.length
        ? !settingsEfforts.includes(option.value)
        : option.value === "Extra" && !reasoningCapability?.extra;
    });
    if (
      settingsEfforts?.length
      && !settingsEfforts.includes(settingsClaudeEffort.value)
    ) {
      settingsClaudeEffort.value = settingsEfforts.includes("Medium")
        ? "Medium"
        : settingsEfforts[0];
    } else if (!reasoningCapability?.extra && settingsClaudeEffort.value === "Extra") {
      settingsClaudeEffort.value = "High";
    }
    settingsClaudeThinking.querySelector('option[value="Off"]').disabled = Boolean(reasoningCapability?.thinkingRequired);
    if (reasoningCapability?.thinkingRequired) {
      settingsClaudeThinking.value = "On";
    }
  });

  settingsThemeMode.addEventListener("click", (e) => {
    const button = e.target.closest(".theme-segment");
    if (!button) return;
    setThemeModeControl(button.getAttribute("data-theme-mode"));
  });

  settingsCloseBtn.addEventListener("click", () => {
    settingsModal.classList.add("hidden");
  });

  settingsModal.addEventListener("click", (e) => {
    if (e.target === settingsModal) {
      settingsModal.classList.add("hidden");
    }
  });

  // Settings tab selection
  settingsModal.querySelectorAll(".settings-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-target");
      activateSettingsTab(targetId);
    });
  });

  // Save settings
  settingsSaveBtn.addEventListener("click", () => {
    currentCodexEffort = settingsCodexEffort.value;
    currentCodexSpeed = settingsCodexSpeed.value;
    currentClaudeEffort = settingsClaudeEffort.value;
    currentClaudeThinking = settingsClaudeThinking.value === "On";
    applyModelSelection(settingsDefaultModel.value);

    // Update active dropdown element highlight
    modelDropdown.querySelectorAll(".dropdown-item").forEach(item => {
      if (item.getAttribute("data-value") === currentModel) {
        item.classList.add("active");
      } else {
        item.classList.remove("active");
      }
    });

    currentTarget = settingsDefaultTarget.value;
    currentTargetText.textContent = currentTarget;
    targetDropdown.querySelectorAll(".dropdown-item").forEach(item => {
      if (item.getAttribute("data-value") === currentTarget) {
        item.classList.add("active");
      } else {
        item.classList.remove("active");
      }
    });

    if (recognition) {
      recognition.lang = settingsSpeechLang.value;
    }

    
    if (settingsWhisperKey && settingsWhisperKey.value.trim()) {
      const newKey = settingsWhisperKey.value.trim();
      fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ groq_api_key: newKey })
      }).then(r => r.json()).then(d => {
        console.log("Whisper settings updated:", d);
        settingsWhisperKey.value = "";
        loadServerSettings();
      }).catch(err => console.error("Failed to update Whisper key:", err));
    }

    currentThemeMode = settingsThemeMode.querySelector(".theme-segment.active")?.getAttribute("data-theme-mode") || "system";
    applyThemeMode();
    saveAppPreferences();
    refreshUsageDisplay();
    settingsModal.classList.add("hidden");
  });

  // --- Resource Usage limits panel logic ---
  const usageBtn = document.getElementById("usageBtn");
  const usagePopup = document.getElementById("usagePopup");
  const usageToggleSwitch = document.getElementById("usageToggleSwitch");

  // Data structure for limits (with realistic fallback defaults)
  let usageData = {
    geminiWeeklyPercent: 1.2,
    geminiHourlyPercent: 0.5,
    claudeWeeklyPercent: 2.5,
    claudeHourlyPercent: 1.8,
    gptWeeklyPercent: 0,
    gptHourlyPercent: 0,

    geminiWeeklyUsed: 120000,
    geminiWeeklyLimit: 10000000,
    geminiHourlyUsed: 5000,
    geminiHourlyLimit: 1000000,

    claudeWeeklyUsed: 2500000,
    claudeWeeklyLimit: 100000000,
    claudeHourlyUsed: 180000,
    claudeHourlyLimit: 10000000,

    gptWeeklyUsed: 0,
    gptWeeklyLimit: 100000000,
    gptHourlyUsed: 0,
    gptHourlyLimit: 10000000,
    codexRateLimits: null,
    codexUsageNote: "Codex GPT models use your ChatGPT/Codex account rate limit."
  };

  async function fetchUsageLimits() {
    if (!canUseProtectedWorkspaceApis()) {
      handleProtectedApiUnauthorized();
      return;
    }
    try {
      const response = await fetch("/api/usage-limits");
      if (response.status === 401) {
        handleProtectedApiUnauthorized();
        return;
      }
      if (response.ok) {
        usageData = await response.json();
        refreshUsageDisplay();
      }
    } catch (err) {
      console.error("Error loading usage limits:", err);
    }
  }

  usageBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    usagePopup.classList.toggle("hidden");
    if (!usagePopup.classList.contains("hidden")) {
      fetchUsageLimits();
    }
  });

  // Toggle click usage vs remaining
  usageToggleSwitch.querySelectorAll(".toggle-mode-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      usageToggleSwitch.querySelectorAll(".toggle-mode-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      const mode = btn.getAttribute("data-mode");
      updateUsageDataDisplay(mode);
    });
  });

  function refreshUsageDisplay() {
    const activeToggleBtn = usageToggleSwitch ? usageToggleSwitch.querySelector(".toggle-mode-btn.active") : null;
    const mode = activeToggleBtn ? activeToggleBtn.getAttribute("data-mode") : "usage";
    updateUsageDataDisplay(mode);
  }

  function getUsageBucketForCurrentModel() {
    if (isCodexModel(currentModel)) {
      return {
        key: "gpt",
        title: "GPT Models (Codex / ChatGPT)",
        badge: "Codex GPT usage",
        note: "Codex models draw from your ChatGPT/Codex GPT usage budget."
      };
    }
    if (isXaiModel(currentModel)) {
      return {
        key: "xai",
        title: "Grok Models (xAI)",
        badge: "xAI account usage",
        note: usageData.xaiUsageNote
          || "Grok usage and billing are managed by your xAI account."
      };
    }
    if (isMuseModel(currentModel)) {
      return {
        key: "muse",
        title: "Muse Models (Meta AI)",
        badge: "Meta AI usage",
        note: "Muse Code usage is managed by Meta Model API."
      };
    }

    const catalogBucket = getCatalogModel(currentModel)?.usage_bucket;
    const lowerModel = getModelLabel(currentModel).toLowerCase();
    if (catalogBucket === "gemini" || lowerModel.includes("gemini")) {
      return {
        key: "gemini",
        title: "Gemini Models",
        badge: "Your Plan: Google AI Ultra",
        note: ""
      };
    }
    if (catalogBucket === "gpt" || lowerModel.includes("gpt") || lowerModel.includes("kimi")) {
      if (lowerModel.includes("kimi")) {
        return {
          key: "gpt",
          title: "Kimi Models",
          badge: "KookAI Kimi usage",
          note: "Kimi usage is grouped in the KookAI model usage budget."
        };
      }
      return {
        key: "gpt",
        title: "GPT Models",
        badge: "OpenAI GPT usage",
        note: ""
      };
    }
    return {
      key: "claude",
      title: "Claude Models",
      badge: "Your Plan: Claude Pro",
      note: ""
    };
  }

  function formatCodexResetDate(timestampSeconds) {
    if (!timestampSeconds) return "";
    try {
      return new Date(timestampSeconds * 1000).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric"
      });
    } catch (_) {
      return "";
    }
  }

  function formatCodexWindowLabel(windowDurationMins) {
    if (windowDurationMins === 10080) return "Weekly Limit";
    if (windowDurationMins === 300) return "Five Hour Limit";
    if (windowDurationMins && windowDurationMins >= 60) {
      const hours = windowDurationMins / 60;
      return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} Hour Limit`;
    }
    return "Usage Limit";
  }

  function updateUsageDataDisplay(mode) {
    const isUsage = (mode === "usage");
    const activeBucket = getUsageBucketForCurrentModel();

    // Update main button chart based on selected model
    const codexPrimary = isCodexModel(currentModel) ? usageData.codexRateLimits?.primary : null;
    const activeHourlyPercent = codexPrimary
      ? Number(codexPrimary.usedPercent || 0)
      : Number(usageData[`${activeBucket.key}HourlyPercent`] || 0);
    const mainVal = isUsage ? activeHourlyPercent : Math.max(0, 100 - activeHourlyPercent);

    const mainCircle = document.getElementById("mainUsageBtnChartCircle");
    if (mainCircle) {
      mainCircle.setAttribute("stroke-dasharray", `${mainVal}, 100`);
    }

    function updateSection(dataPrefix, limitName, elementPrefix = dataPrefix) {
      const usedPercent = Number(usageData[`${dataPrefix}Percent`] || 0);
      const usedTokens = Number(usageData[`${dataPrefix}Used`] || 0);
      const limitTokens = Number(usageData[`${dataPrefix}Limit`] || 0);

      const val = isUsage ? usedPercent : Math.max(0, 100 - usedPercent);
      const percentEl = document.getElementById(`${elementPrefix}Percent`);
      const chartEl = document.getElementById(`${elementPrefix}Chart`);
      const descEl = document.getElementById(`${elementPrefix}Desc`);

      if (percentEl) percentEl.textContent = `${val.toFixed(1)}%`;
      if (chartEl) chartEl.setAttribute("stroke-dasharray", `${val}, 100`);

      if (descEl) {
        if (isUsage) {
          descEl.textContent = `You have used ${usedTokens.toLocaleString()} tokens (${usedPercent.toFixed(1)}%) of your ${limitName} limit.`;
        } else {
          const remainingTokens = Math.max(0, limitTokens - usedTokens);
          const remainingPercent = Math.max(0, 100 - usedPercent);
          descEl.textContent = `You have ${remainingTokens.toLocaleString()} tokens (${remainingPercent.toFixed(1)}%) remaining of your ${limitName} limit.`;
        }
      }
    }

    const geminiSection = document.getElementById("usageGeminiSection");
    const secondarySection = document.getElementById("usageSecondarySection");
    const showGemini = activeBucket.key === "gemini";
    geminiSection?.classList.toggle("hidden", !showGemini);
    secondarySection?.classList.toggle("hidden", showGemini);

    if (showGemini) {
      updateSection("geminiWeekly", "weekly");
      updateSection("geminiHourly", "5-hour");
      return;
    }

    const secondaryTitle = document.getElementById("secondaryUsageTitle");
    const secondaryBadge = document.getElementById("secondaryUsageBadge");
    const secondaryNote = document.getElementById("secondaryUsageNote");
    if (secondaryTitle) secondaryTitle.textContent = activeBucket.title;
    if (secondaryBadge) secondaryBadge.textContent = activeBucket.badge;
    if (secondaryNote) {
      const note = isCodexModel(currentModel) ? (usageData.codexUsageNote || activeBucket.note) : activeBucket.note;
      secondaryNote.textContent = note;
      secondaryNote.classList.toggle("hidden", !note);
    }

    if (isCodexModel(currentModel) && usageData.codexRateLimits) {
      const weeklyRow = document.getElementById("secondaryWeeklyRow");
      const hourlyRow = document.getElementById("secondaryHourlyRow");
      const renderCodexWindow = (windowData, elementPrefix, fallbackLabel) => {
        if (!windowData) return false;
        const usedPercent = Number(windowData.usedPercent || 0);
        const remainingPercent = Number(windowData.remainingPercent ?? Math.max(0, 100 - usedPercent));
        const val = isUsage ? usedPercent : remainingPercent;
        const resetDate = formatCodexResetDate(windowData.resetsAt);
        const percentEl = document.getElementById(`${elementPrefix}Percent`);
        const chartEl = document.getElementById(`${elementPrefix}Chart`);
        const descEl = document.getElementById(`${elementPrefix}Desc`);
        const rowEl = document.getElementById(elementPrefix === "claudeWeekly" ? "secondaryWeeklyRow" : "secondaryHourlyRow");
        const labelEl = rowEl?.querySelector(".usage-label");
        if (rowEl) rowEl.classList.remove("hidden");
        if (labelEl) labelEl.textContent = formatCodexWindowLabel(windowData.windowDurationMins) || fallbackLabel;
        if (percentEl) percentEl.textContent = `${val.toFixed(0)}%`;
        if (chartEl) chartEl.setAttribute("stroke-dasharray", `${val}, 100`);
        if (descEl) {
          descEl.textContent = isUsage
            ? `Used ${usedPercent.toFixed(0)}% of your Codex account limit${resetDate ? `; resets ${resetDate}` : ""}.`
            : `${remainingPercent.toFixed(0)}% remaining${resetDate ? `; resets ${resetDate}` : ""}.`;
        }
        return true;
      };
      renderCodexWindow(usageData.codexRateLimits.primary, "claudeWeekly", "Weekly Limit");
      const hasSecondary = renderCodexWindow(usageData.codexRateLimits.secondary, "claudeHourly", "Five Hour Limit");
      if (weeklyRow) weeklyRow.classList.remove("hidden");
      if (hourlyRow) hourlyRow.classList.toggle("hidden", !hasSecondary);
      if (secondaryNote && typeof usageData.codexRateLimits.availableResets === "number") {
        secondaryNote.textContent = `${secondaryNote.textContent} ${usageData.codexRateLimits.availableResets} available resets.`;
      }
      return;
    }
    if (isXaiModel(currentModel) || isMuseModel(currentModel)) {
      document.getElementById("secondaryWeeklyRow")?.classList.add("hidden");
      document.getElementById("secondaryHourlyRow")?.classList.add("hidden");
      return;
    }

    document.getElementById("secondaryWeeklyRow")?.classList.remove("hidden");
    document.getElementById("secondaryHourlyRow")?.classList.remove("hidden");
    updateSection(`${activeBucket.key}Weekly`, "weekly", "claudeWeekly");
    updateSection(`${activeBucket.key}Hourly`, "5-hour", "claudeHourly");
  }

  // Initialize display on load
  refreshUsageDisplay();

  // Close popup when clicking outside
  document.addEventListener("click", (e) => {
    if (!usagePopup.classList.contains("hidden") && !usagePopup.contains(e.target) && e.target !== usageBtn && !usageBtn.contains(e.target)) {
      usagePopup.classList.add("hidden");
    }
  });

  // --- Pairing Modal Logic ---
  const linkMobileBtn = document.getElementById("linkMobileBtn");
  const pairingModal = document.getElementById("pairingModal");
  const closePairingModalBtn = document.getElementById("closePairingModalBtn");
  const pairingQrImg = document.getElementById("pairingQrImg");
  const pairingPinText = document.getElementById("pairingPinText");

  if (linkMobileBtn) {
    const qrLoader = document.getElementById("qrLoader");

    // Smooth transition from loader to QR code when loaded
    pairingQrImg.addEventListener("load", () => {
      if (qrLoader) qrLoader.style.display = "none";
      pairingQrImg.style.display = "block";
      setTimeout(() => {
        pairingQrImg.style.opacity = "1";
      }, 50);
    });

    linkMobileBtn.addEventListener("click", async () => {
      try {
        pairingPinText.textContent = "Loading...";

        // Reset loader/image states
        if (qrLoader) qrLoader.style.display = "flex";
        pairingQrImg.style.display = "none";
        pairingQrImg.style.opacity = "0";
        pairingQrImg.src = "";

        pairingModal.classList.remove("hidden");

        const response = await fetch("/api/pairing-code");
        if (!response.ok) throw new Error("Failed to fetch pairing code");

        const data = await response.json();
        const pin = data.pin;
        pairingPinText.textContent = pin;
        // The QR contains only the mobile deep link. Pairing codes are generated
        // from localhost and Cloudflare does not serve the web landing page.
        const pairingLink = data.pairing_deep_link || `kookai://pair?pin=${encodeURIComponent(pin)}`;
        pairingQrImg.src = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(pairingLink)}&size=200x200&color=0f172a`;
      } catch (err) {
        console.error(err);
        pairingPinText.textContent = "ERROR";
        if (qrLoader) qrLoader.style.display = "none";
      }
    });
  }

  if (closePairingModalBtn) {
    closePairingModalBtn.addEventListener("click", () => {
      pairingModal.classList.add("hidden");
    });
  }

  // Helper for escaping HTML strings safely
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // --- Local Access State & Logic ---
  const authLoggedOut = document.getElementById("authLoggedOut");
  const authLoggedIn = document.getElementById("authLoggedIn");
  const userProfileBadge = document.getElementById("userProfileBadge");
  const userMenuDropdown = document.getElementById("userMenuDropdown");
  const userAvatar = document.getElementById("userAvatar");
  const userName = document.getElementById("userName");
  const userEmail = document.getElementById("userEmail");
  const userRoleBadge = document.getElementById("userRoleBadge");

  function initLocalAccessUI() {
    if (authLoggedOut) authLoggedOut.classList.add("hidden");
    if (authLoggedIn) authLoggedIn.classList.remove("hidden");
    if (userName) userName.textContent = "Local Workspace";
    if (userEmail) userEmail.textContent = "localhost only";
    if (userRoleBadge) {
      userRoleBadge.classList.remove("hidden");
      userRoleBadge.textContent = "Local";
    }
    if (userAvatar) {
      userAvatar.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'><rect width='32' height='32' rx='16' fill='%232563eb'/><text x='50%25' y='50%25' dominant-baseline='central' text-anchor='middle' fill='white' font-family='sans-serif' font-weight='bold' font-size='13'>L</text></svg>";
      userAvatar.style.display = "block";
    }
  }

  if (userProfileBadge) {
    userProfileBadge.addEventListener("click", (e) => {
      e.stopPropagation();
      if (userMenuDropdown) {
        userMenuDropdown.classList.toggle("hidden");
      }
    });
  }

  document.addEventListener("click", (e) => {
    if (userMenuDropdown && !userMenuDropdown.contains(e.target) && !userProfileBadge?.contains(e.target)) {
      userMenuDropdown.classList.add("hidden");
    }
  });

  // Run initializations
  initApp();
});
