declare const process: any;

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface RunningTask {
  taskId: string;
  isPendingStart?: boolean;
  workspace: string;
  conversationId: string;
  originalConversationId: string;
  message: string;
  status: string;
  events: { seq: number; type: string; message: string }[];
  lastSeq: number;
}

function assert(cond: boolean, message: string) {
  if (!cond) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function runMobileNewConversationIsolationTests() {
  console.log('=== Running Mobile New Conversation Isolation Tests ===');

  const state = {
    convoViewSeq: 0,
    activeConvoId: 'convo_working_1',
    selectedProject: 'KookAI',
    loading: false,
    messages: [{ role: 'user', content: 'งานหน้าต่างที่ 1 กำลังทำอยู่' }] as Message[],
    taskProgressEvents: [] as { seq: number; type: string; message: string }[],
  };

  const runningTasks: Record<string, RunningTask> = {
    task_1: {
      taskId: 'task_1',
      workspace: 'KookAI',
      conversationId: 'convo_working_1',
      originalConversationId: 'convo_working_1',
      message: 'งานหน้าต่างที่ 1 กำลังทำอยู่',
      status: 'running',
      events: [{ seq: 0, type: 'progress', message: 'Thinking...' }],
      lastSeq: 0,
    },
  };

  const getRunningTaskForConversation = (cid?: string | null) => {
    if (!cid) return null;
    return (
      Object.values(runningTasks).find(
        (t) =>
          (t.status === 'running' || t.status === 'queued') &&
          (t.conversationId === cid || t.originalConversationId === cid)
      ) || null
    );
  };

  const syncActiveViewTaskState = (convoIdOverride?: string) => {
    const targetCid = convoIdOverride !== undefined ? convoIdOverride : state.activeConvoId;
    const currentTask = getRunningTaskForConversation(targetCid);
    if (currentTask) {
      state.loading = true;
      state.taskProgressEvents = [...currentTask.events];
    } else {
      state.loading = false;
      state.taskProgressEvents = [];
    }
  };

  const slowSecureStoreRead = () => delay(60).then(() => 'Gemini 4 Carbon (High)');
  const slowActiveTasksApi = () =>
    delay(60).then(() => ({
      tasks: [
        {
          task_id: 'task_1',
          workspace: 'KookAI',
          conversation_id: 'convo_working_1',
          original_conversation_id: 'convo_working_1',
          message: 'งานหน้าต่างที่ 1 กำลังทำอยู่',
          status: 'running',
          events: [{ seq: 0, type: 'progress', message: 'Thinking...' }],
        },
      ],
    }));

  const startNewChat = async () => {
    const mySeq = ++state.convoViewSeq;
    const newId = `temp_${state.selectedProject}_new123`;
    state.activeConvoId = newId;
    state.messages = [];
    syncActiveViewTaskState(newId);
    await slowSecureStoreRead();
    if (state.convoViewSeq === mySeq && state.activeConvoId === newId) {
      // Model restored safely only if still on newId
    }
    return newId;
  };

  const checkAndAttachActiveTask = async (currentConvoId?: string) => {
    const expectedSeq = state.convoViewSeq;
    const convoId = currentConvoId !== undefined ? currentConvoId : state.activeConvoId;
    const res = await slowActiveTasksApi();
    res.tasks.forEach((t) => {
      if (!runningTasks[t.task_id]) {
        runningTasks[t.task_id] = {
          taskId: t.task_id,
          workspace: t.workspace,
          conversationId: t.conversation_id,
          originalConversationId: t.original_conversation_id,
          message: t.message,
          status: t.status,
          events: t.events,
          lastSeq: 0,
        };
      }
    });
    if (state.convoViewSeq !== expectedSeq || state.activeConvoId !== convoId) {
      syncActiveViewTaskState();
      return;
    }
    const activeTask = getRunningTaskForConversation(convoId);
    if (activeTask?.message) {
      state.messages = [...state.messages, { role: 'user', content: activeTask.message }];
      syncActiveViewTaskState(activeTask.conversationId || convoId);
    }
  };

  // Test 1: In-flight checkAndAttachActiveTask started while viewing convo_working_1
  // MUST NOT leak convo_working_1's message or loading state when user taps + New Conversation!
  syncActiveViewTaskState('convo_working_1');
  assert(state.loading === true, 'convo_working_1 should initially show loading');
  const pendingAttach = checkAndAttachActiveTask('convo_working_1');

  // User taps + New Conversation BEFORE checkAndAttachActiveTask or SecureStore finishes!
  const newChatPromise = startNewChat();
  // Synchronous check (0ms after tap, before SecureStore resolves!):
  assert(state.activeConvoId === 'temp_KookAI_new123', 'activeConvoId must switch synchronously on New Conversation tap');
  assert(state.messages.length === 0, 'messages must clear synchronously on New Conversation tap');
  assert(state.loading === false, 'loading must clear synchronously on New Conversation tap');
  assert(state.taskProgressEvents.length === 0, 'taskProgressEvents must clear synchronously');

  await Promise.all([pendingAttach, newChatPromise]);

  assert(state.activeConvoId === 'temp_KookAI_new123', 'activeConvoId must remain on New Conversation after stale attach resolves');
  assert(state.messages.length === 0, 'working conversation message must NOT leak into New Conversation');
  assert(state.loading === false, 'working conversation loading spinner must NOT leak into New Conversation');

  // Test 2: When task_1 finishes in background while user is on temp_KookAI_new123,
  // reply must NOT append into temp_KookAI_new123
  const finishingTask = runningTasks['task_1'];
  delete runningTasks['task_1'];
  const resolvedCid = 'agy_resolved_111';
  const isViewingFinishingConvo =
    state.activeConvoId === finishingTask.originalConversationId ||
    state.activeConvoId === finishingTask.conversationId ||
    state.activeConvoId === resolvedCid;
  assert(isViewingFinishingConvo === false, 'New Conversation must not match finishing task');
  assert(state.messages.length === 0, 'New Conversation remains completely clean after background task finishes');

  console.log('✓ Mobile New Conversation isolation tests passed!');
}

runMobileNewConversationIsolationTests().catch((err) => {
  console.error(err);
  process.exit(1);
});
