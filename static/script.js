document.addEventListener("DOMContentLoaded", () => {
  // UI Panels
  const chatPanel = document.getElementById("chatPanel");
  const historyPanel = document.getElementById("historyPanel");

  // Tab Menu elements
  const historyMenuBtn = document.getElementById("historyMenuBtn");
  const newConvoBtn = document.getElementById("newConvoBtn");
  const headerProject = document.getElementById("headerProject");
  const headerConvo = document.getElementById("headerConvo");

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
  const targetBtn = document.getElementById("targetBtn");
  const projectPickerBtn = document.getElementById("projectPickerBtn");

  // Dropdown Menus
  const workspaceDropdown = document.getElementById("workspaceDropdown");
  const modelDropdown = document.getElementById("modelDropdown");
  const targetDropdown = document.getElementById("targetDropdown");

  // Display texts
  const currentModelText = document.getElementById("currentModelText");
  const currentTargetText = document.getElementById("currentTargetText");

  // State Variables
  let currentWorkspace = "agy";
  let currentModel = "Gemini 3.5 Flash (High)";
  let currentTarget = "Sandbox";
  let currentThemeMode = "system";
  let activeConversationId = ""; // Current chat session ID
  let workspaceFiles = [];
  let projectsList = [];
  let conversationsList = [];
  let isRecording = false;
  let recognition = null;

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
    localStorage.setItem("antigravity_model", currentModel);
    localStorage.setItem("antigravity_target", currentTarget);
    localStorage.setItem("antigravity_theme", currentThemeMode);
  }

  function loadAppPreferences() {
    const savedModel = localStorage.getItem("antigravity_model");
    const savedTarget = localStorage.getItem("antigravity_target");
    const savedThemeMode = localStorage.getItem("antigravity_theme");

    if (savedModel) {
      currentModel = savedModel;
      if (currentModelText) currentModelText.textContent = currentModel;
      modelDropdown.querySelectorAll(".dropdown-item").forEach(item => {
        if (item.getAttribute("data-value") === currentModel) {
          item.classList.add("active");
        } else {
          item.classList.remove("active");
        }
      });
    }

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

  function initApp() {
    loadAppPreferences();
    fetchUsageLimits();
    refreshUsageDisplay();
    startNewConversation(); // Generate initial UUID
    loadProjectsAndConversations();
    fetchWorkspaceFiles();
  }

  // --- Fetch Data ---
  function fetchWorkspaceFiles() {
    fetch("/api/files")
      .then(res => res.json())
      .then(data => {
        workspaceFiles = data.files || [];
      })
      .catch(err => console.error("Error loading files:", err));
  }

  function loadProjectsAndConversations() {
    // 1. Load Projects List
    fetch("/api/projects")
      .then(res => res.json())
      .then(projData => {
        projectsList = projData.projects;
        if (projData.workspace_dir) {
          const diagWorkspace = document.getElementById("diagWorkspace");
          if (diagWorkspace) {
            diagWorkspace.textContent = projData.workspace_dir;
          }
        }

        // 2. Load Conversations List
        return fetch("/api/conversations");
      })
      .then(res => res.json())
      .then(convoData => {
        conversationsList = convoData.conversations;

        renderProjectsTree();
        renderWorkspaceDropdown();
      })
      .catch(err => console.error("Error loading workspace metadata:", err));
  }

  // --- Render Projects Sidebar ---
  function renderProjectsTree() {
    const treeContainer = document.getElementById("projectsTree");
    treeContainer.innerHTML = "";

    // Group conversations by project
    const convoByProject = {};
    conversationsList.forEach(c => {
      if (!convoByProject[c.project]) {
        convoByProject[c.project] = [];
      }
      convoByProject[c.project].push(c);
    });

    // Populate each project node
    projectsList.forEach(project => {
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
    workspaceDropdown.innerHTML = `<div class="dropdown-header">Workspaces</div>`;
    projectsList.forEach(project => {
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
    switchNavigationPanel(chatPanel);
    historyMenuBtn.classList.remove("active");
  }

  function showHistoryTab() {
    switchNavigationPanel(historyPanel);
    historyMenuBtn.classList.add("active");

    // Load History list content
    renderHistoryList();
  }
  historyMenuBtn.addEventListener("click", showHistoryTab);

  // --- Render Conversation History Panel (Screenshot 2) ---
  function renderHistoryList(filterQuery = "") {
    historyList.innerHTML = "";

    fetch("/api/chat-history")
      .then(res => res.json())
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
    { name: "/goal", desc: "Initiate goal mode checklist", type: "Command" },
    { name: "/browser", desc: "Launch browser automation tool", type: "Command" },
    { name: "/grill-me", desc: "Launch requirements audit survey", type: "Command" },
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

    if (role === "assistant" && content.startsWith('{"type": "question"')) {
      try {
        const qObj = JSON.parse(content);
        renderQuestionCard(bubble, qObj, isDisabled);
      } catch(e) {
        bubble.innerHTML = window.marked ? window.marked.parse(content) : content;
      }
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
    const rect = btn.getBoundingClientRect();
    if (direction === "up") {
      dropdown.style.top = "";
      dropdown.style.bottom = `${window.innerHeight - rect.top + 8}px`;
      dropdown.style.left = `${rect.left}px`;
    } else {
      dropdown.style.bottom = "";
      dropdown.style.top = `${rect.bottom + 8}px`;
      dropdown.style.left = `${rect.left}px`;
    }
  }

  window.addEventListener("click", (e) => {
    if (workspaceDropdown && !workspaceDropdown.contains(e.target) && (!projectPickerBtn || !projectPickerBtn.contains(e.target))) {
      workspaceDropdown.classList.add("hidden");
    }
    if (!modelBtn.contains(e.target) && !modelDropdown.contains(e.target)) {
      modelDropdown.classList.add("hidden");
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
    if (modelDropdown.classList.contains("hidden")) {
      positionDropdown(modelBtn, modelDropdown, "up");
    } else {
      modelDropdown.classList.add("hidden");
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
    currentModel = val;
    currentModelText.textContent = val;
    modelDropdown.classList.add("hidden");
    saveAppPreferences();
    refreshUsageDisplay();
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
  const settingsDefaultTarget = document.getElementById("settingsDefaultTarget");
  const settingsSpeechLang = document.getElementById("settingsSpeechLang");
  const settingsThemeMode = document.getElementById("settingsThemeMode");

  settingsBtn.addEventListener("click", () => {
    // Populate with current configurations
    settingsDefaultModel.value = currentModel;
    settingsDefaultTarget.value = currentTarget;
    setThemeModeControl(currentThemeMode);
    if (recognition) {
      settingsSpeechLang.value = recognition.lang || "th-TH";
    }
    settingsModal.classList.remove("hidden");
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
      settingsModal.querySelectorAll(".settings-tab").forEach(t => t.classList.remove("active"));
      settingsModal.querySelectorAll(".settings-tab-content").forEach(c => c.classList.add("hidden"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-target");
      document.getElementById(targetId).classList.remove("hidden");
    });
  });

  // Save settings
  settingsSaveBtn.addEventListener("click", () => {
    currentModel = settingsDefaultModel.value;
    currentModelText.textContent = currentModel;

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

    geminiWeeklyUsed: 120000,
    geminiWeeklyLimit: 10000000,
    geminiHourlyUsed: 5000,
    geminiHourlyLimit: 1000000,

    claudeWeeklyUsed: 2500000,
    claudeWeeklyLimit: 100000000,
    claudeHourlyUsed: 180000,
    claudeHourlyLimit: 10000000
  };

  async function fetchUsageLimits() {
    try {
      const response = await fetch("/api/usage-limits");
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

  function updateUsageDataDisplay(mode) {
    const isUsage = (mode === "usage");

    // Update main button chart based on selected model
    const isGemini = currentModel.toLowerCase().includes("gemini");
    const activeHourlyPercent = isGemini ? usageData.geminiHourlyPercent : usageData.claudeHourlyPercent;
    const mainVal = isUsage ? activeHourlyPercent : (100 - activeHourlyPercent);

    const mainCircle = document.getElementById("mainUsageBtnChartCircle");
    if (mainCircle) {
      mainCircle.setAttribute("stroke-dasharray", `${mainVal}, 100`);
    }

    function updateSection(prefix, limitName) {
      const usedPercent = usageData[`${prefix}Percent`];
      const usedTokens = usageData[`${prefix}Used`];
      const limitTokens = usageData[`${prefix}Limit`];

      const val = isUsage ? usedPercent : (100 - usedPercent);
      const percentEl = document.getElementById(`${prefix}Percent`);
      const chartEl = document.getElementById(`${prefix}Chart`);
      const descEl = document.getElementById(`${prefix}Desc`);

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

    updateSection("geminiWeekly", "weekly");
    updateSection("geminiHourly", "5-hour");
    updateSection("claudeWeekly", "weekly");
    updateSection("claudeHourly", "5-hour");
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
        const pairingBaseUrl = (data.pairing_url || window.location.origin).replace(/\/$/, "");

        pairingPinText.textContent = pin;
        // Generate QR code using the free qrserver API. iPhone Camera opens HTTPS more reliably;
        // the landing page redirects into the app with antigravity://pair?pin=...
        const pairingLink = `${pairingBaseUrl}/pair.html?pin=${encodeURIComponent(pin)}`;
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

  if (pairingModal) {
    pairingModal.addEventListener("click", (e) => {
      if (e.target === pairingModal) {
        pairingModal.classList.add("hidden");
      }
    });
  }

  // Run initializations
  initApp();
});
