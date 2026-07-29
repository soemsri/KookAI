import React, { useState, useEffect, useRef } from 'react';
import { StyleSheet, Text, View, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, Alert, KeyboardAvoidingView, Platform, StatusBar, Animated, useColorScheme, Modal, Vibration, Easing, Keyboard, Image, Linking, Switch } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import * as SecureStore from 'expo-secure-store';
import { apiCall, clearConnection, uploadMedia, loadConnection, getActiveBaseUrl } from '../utils/api';
import {
  isModelCatalog,
  ModelCatalog,
  readCachedModelCatalog,
  writeCachedModelCatalog,
} from '../utils/modelCatalog';
import Svg, { Circle } from 'react-native-svg';
import * as DocumentPicker from 'expo-document-picker';
// Mock Audio namespaces and classes to avoid importing deprecated expo-av
namespace Audio {
  export type Sound = any;
  export type Recording = any;
}
const Audio = {
  requestPermissionsAsync: async () => ({ granted: false }),
  setAudioModeAsync: async (...args: any[]) => {},
  Recording: {
    createAsync: async (...args: any[]) => { throw new Error("Audio recording is not supported in this version."); }
  },
  RecordingOptionsPresets: {
    HIGH_QUALITY: {}
  },
  Sound: {
    createAsync: async (...args: any[]) => { throw new Error("Audio playback is not supported in this version."); }
  }
};

interface Message {
  role: 'user' | 'assistant';
  content: string;
  disabled?: boolean;
}

interface Conversation {
  id: string;
  title: string;
  project: string;
  provider?: AgentProvider;
  model?: string;
  effort?: CodexEffort | ClaudeEffort;
  speed?: CodexSpeed;
  thinking?: boolean;
}

interface ChatScreenProps {
  onDisconnect: () => void;
}

interface QuestionPayload {
  type: 'question';
  question: string;
  options: string[];
  allow_other?: boolean;
}

interface PromptSuggestion {
  name: string;
  desc: string;
  type: string;
}

interface QueuedPrompt {
id: string;
content: string;
model: string;
provider: AgentProvider;
effort: CodexEffort | ClaudeEffort;
speed: CodexSpeed;
thinking: boolean;
target: string;
project: string;
conversationId: string;
}

interface ChatTaskEvent {
seq: number;
type: 'progress' | 'error';
message: string;
}

type SettingsTab = 'general' | 'diagnostics';
type ThemeMode = 'system' | 'light' | 'dark';
type AgentProvider = 'agy' | 'codex' | 'claude' | 'kimi';
type CodexEffort = 'Light' | 'Medium' | 'High' | 'Extra High' | 'Ultra';
type CodexSpeed = 'Standard' | 'Fast';
type ClaudeEffort = 'Low' | 'Medium' | 'High' | 'Extra' | 'Max';
type UsageBucketKey = 'gemini' | 'claude' | 'gpt';
type UsagePeriodKey = 'Weekly' | 'Hourly';

interface ModelOption {
  value: string;
  label?: string;
  desc: string;
  provider: AgentProvider;
  badge?: string;
  usageBucket?: UsageBucketKey;
  supportsUltra?: boolean;
  supportsFast?: boolean;
  supportsClaudeEffort?: boolean;
  supportsClaudeExtra?: boolean;
  thinkingRequired?: boolean;
}

const colors = {
  dark: {
    bgPrimary: '#0f1115',     // Sidebar background
    bgSecondary: '#181b22',   // Chat panel background
    bgActive: '#222630',      // Selected conversation
    bgInput: '#22262f',       // Text input container background
    borderColor: '#2e3543',
    textPrimary: '#f3f4f6',
    textSecondary: '#9ca3af',
    textMuted: '#6b7280',
    accent: '#3b82f6',
    statusGreen: '#34d399',
    statusRed: '#f87171',
  },
  light: {
    bgPrimary: '#f8f9fa',
    bgSecondary: '#ffffff',
    bgActive: '#eaeaea',
    bgInput: '#eaeaea',
    borderColor: '#e5e7eb',
    textPrimary: '#1f2937',
    textSecondary: '#4b5563',
    textMuted: '#9ca3af',
    accent: '#2563eb',
    statusGreen: '#10b981',
    statusRed: '#ef4444',
  }
};

const FALLBACK_MODELS: ModelOption[] = [
  { value: "Gemini 3.6 Flash (High)", desc: "Fastest response, ideal for coding tasks", provider: "agy" },
  { value: "Gemini 3.6 Flash (Medium)", desc: "Balanced speed and performance", provider: "agy" },
  { value: "Gemini 3.6 Flash (Low)", desc: "Fast, low resource usage", provider: "agy" },
  { value: "Gemini 3.5 Flash (High)", desc: "Fastest response, ideal for coding tasks", provider: "agy" },
  { value: "Gemini 3.5 Flash (Medium)", desc: "Balanced speed and performance", provider: "agy" },
  { value: "Gemini 3.5 Flash (Low)", desc: "Fast, low resource usage", provider: "agy" },
  { value: "Gemini 3.1 Pro (High)", desc: "Deep reasoning, complex tasks", provider: "agy" },
  { value: "Gemini 3.1 Pro (Low)", desc: "Enhanced logic reasoning", provider: "agy" },
  { value: "Claude Sonnet 4.6 (Thinking)", desc: "Advanced reasoning with thinking trace", provider: "agy" },
  { value: "Claude Opus 4.6 (Thinking)", desc: "Highest reasoning capacity model", provider: "agy" },
  { value: "GPT-OSS 120B (Medium)", desc: "Open-source large scale LLM", provider: "agy" },
  { value: "Kimi K3", desc: "Native multimodal model for long-horizon coding", provider: "kimi", badge: "Kimi", usageBucket: "gpt", thinkingRequired: true },
  { value: "Fable 5", desc: "For your toughest challenges", provider: "claude", supportsClaudeEffort: true, supportsClaudeExtra: true, thinkingRequired: true },
  { value: "Opus 5", desc: "For complex tasks", provider: "claude", supportsClaudeEffort: true, supportsClaudeExtra: true },
  { value: "Sonnet 5", desc: "Most efficient for everyday tasks", provider: "claude", supportsClaudeEffort: true, supportsClaudeExtra: true },
  { value: "Haiku 4.5", desc: "Fastest for quick answers", provider: "claude" },
  { value: "Opus 4.8", desc: "Previous generation Opus", provider: "claude", supportsClaudeEffort: true, supportsClaudeExtra: true },
  { value: "Opus 4.7", desc: "Previous generation Opus", provider: "claude", supportsClaudeEffort: true, supportsClaudeExtra: true },
  { value: "Opus 4.6", desc: "Legacy Opus model", provider: "claude", supportsClaudeEffort: true },
  { value: "Opus 3", desc: "Legacy Opus model", provider: "claude" },
  { value: "Sonnet 4.6", desc: "Previous generation Sonnet", provider: "claude", supportsClaudeEffort: true },
  { value: "5.6 Sol", desc: "Codex for complex, open-ended work", provider: "codex", supportsUltra: true, supportsFast: true },
  { value: "5.6 Terra", desc: "Codex everyday all-rounder", provider: "codex", supportsUltra: true, supportsFast: true },
  { value: "5.6 Luna", desc: "Codex for clear, repeatable work", provider: "codex", supportsFast: true },
  { value: "5.5", desc: "Codex GPT-5.5", provider: "codex", supportsFast: true },
  { value: "5.4", desc: "Codex GPT-5.4", provider: "codex", supportsFast: true },
  { value: "5.4 Mini", desc: "Compact Codex model", provider: "codex" },
];

let activeModelsList: ModelOption[] = FALLBACK_MODELS;
let activeDefaultModel = "Gemini 3.5 Flash (High)";

const catalogToModelOptions = (catalog: ModelCatalog): ModelOption[] => (
  catalog.models
    .filter((model) => model.enabled)
    .map((model) => ({
      value: model.id,
      label: model.label,
      desc: model.description,
      provider: model.provider,
      badge: model.badge,
      usageBucket: model.usage_bucket,
      supportsUltra: model.capabilities.effort.includes('Ultra'),
      supportsFast: model.capabilities.speed.includes('Fast'),
      supportsClaudeEffort: model.provider === 'claude' && model.capabilities.effort.length > 0,
      supportsClaudeExtra: model.capabilities.effort.includes('Extra'),
      thinkingRequired: model.capabilities.thinking_required,
    }))
);

const codexEffortList: { value: CodexEffort; desc: string }[] = [
  { value: "Light", desc: "Quick, well-scoped tasks" },
  { value: "Medium", desc: "Balanced speed and depth" },
  { value: "High", desc: "Difficult multi-step tasks" },
  { value: "Extra High", desc: "Maximum single-agent reasoning" },
  { value: "Ultra", desc: "Parallel subagents for complex work" },
];

const codexSpeedList: { value: CodexSpeed; desc: string }[] = [
  { value: "Standard", desc: "Default speed" },
  { value: "Fast", desc: "1.5x speed, more usage" },
];
const claudeEffortList: { value: ClaudeEffort; desc: string }[] = [
  { value: "Low", desc: "Quick replies to simple questions" },
  { value: "Medium", desc: "Light, casual tasks" },
  { value: "High", desc: "Balanced for everyday work" },
  { value: "Extra", desc: "Complex, detailed work" },
  { value: "Max", desc: "The hardest problems; takes longest" },
];

const getModelOption = (modelName: string) => activeModelsList.find(
  (model) => model.value === modelName || model.label === modelName
);
const getModelLabel = (modelName: string) => getModelOption(modelName)?.label || modelName;
const isCodexModel = (modelName: string) => getModelOption(modelName)?.provider === "codex";
const isClaudeModel = (modelName: string) => getModelOption(modelName)?.provider === "claude";
const isKimiModel = (modelName: string) => getModelOption(modelName)?.provider === "kimi";
const getClaudeEfforts = (modelName: string) => {
  const model = getModelOption(modelName);
  if (!model?.supportsClaudeEffort) return [];
  return model.supportsClaudeExtra
    ? claudeEffortList
    : claudeEffortList.filter((item) => item.value !== "Extra");
};
const getCodexEfforts = (modelName: string) => (
  getModelOption(modelName)?.supportsUltra
    ? codexEffortList
    : codexEffortList.filter((item) => item.value !== "Ultra")
);
const getCodexSpeeds = (modelName: string) => (
  getModelOption(modelName)?.supportsFast
    ? codexSpeedList
    : codexSpeedList.filter((item) => item.value !== "Fast")
);

const getUsageBucketForModel = (modelName: string): {
  key: UsageBucketKey;
  title: string;
  note?: string;
} => {
  const catalogBucket = getModelOption(modelName)?.usageBucket;
  if (isCodexModel(modelName)) {
    return {
      key: 'gpt',
      title: 'GPT Models (Codex / ChatGPT)',
      note: 'Codex models draw from your ChatGPT/Codex GPT usage budget.',
    };
  }
  if (isKimiModel(modelName)) {
    return {
      key: 'gpt',
      title: 'Kimi Models (KookAI)',
      note: 'Kimi usage is grouped in the KookAI model usage budget.',
    };
  }

  const lowered = getModelLabel(modelName).toLowerCase();
  if (catalogBucket === 'gemini' || lowered.includes('gemini')) {
    return { key: 'gemini', title: 'Gemini Models (Google AI Ultra)' };
  }
  if (catalogBucket === 'gpt' || lowered.includes('gpt') || lowered.includes('kimi')) {
    return { key: 'gpt', title: 'GPT Models (KookAI)' };
  }
  return { key: 'claude', title: 'Claude Models (Claude Pro)' };
};

const targetsList = [
  { value: "Sandbox", desc: "Execute in a secure local sandbox" },
  { value: "Real", desc: "Execute directly on your host machine (default)" }
];

const DEFAULT_EXECUTION_TARGET = "Real";

const speechLanguageList = [
  { value: "th-TH", desc: "Thai" },
  { value: "en-US", desc: "English" }
];

const themeModeList: { value: ThemeMode; desc: string }[] = [
  { value: "system", desc: "System" },
  { value: "light", desc: "Light" },
  { value: "dark", desc: "Dark" }
];

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
};

const slashCommands: PromptSuggestion[] = [
  { name: "/goal", desc: "Initiate goal mode checklist", type: "Command" },
  { name: "/browser", desc: "Launch browser automation tool", type: "Command" },
  { name: "/grill-me", desc: "Launch requirements audit survey", type: "Command" },
  { name: "/help", desc: "Show prompt help context panel", type: "Command" },
];

const USAGE_LIMIT_TIMEOUT_MS = 5000;
const DEFAULT_USAGE_LIMIT_DATA = {
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
  codexUsageNote: "Codex GPT models use your ChatGPT/Codex account rate limit.",
};

const getSpeechRecognitionModule = () => {
  try {
    return require('expo-speech-recognition').ExpoSpeechRecognitionModule;
  } catch (err) {
    console.log("expo-speech-recognition native module not loaded:", err);
    return null;
  }
};

const parseQuestionPayload = (content: string): QuestionPayload | null => {
  try {
    const parsed = JSON.parse(content);
    if (
      parsed?.type === 'question' &&
      typeof parsed.question === 'string' &&
      Array.isArray(parsed.options)
    ) {
      return {
        type: 'question',
        question: parsed.question,
        options: parsed.options.filter((option: unknown) => typeof option === 'string'),
        allow_other: Boolean(parsed.allow_other),
      };
    }
  } catch {
    return null;
  }

  return null;
};

const getBadgeStyles = (modelName: string, isDark: boolean) => {
  const catalogBadge = getModelOption(modelName)?.badge;
  const name = getModelLabel(modelName).toLowerCase();
  if (isCodexModel(modelName)) {
    return isDark
      ? { text: catalogBadge || 'Codex', bg: 'rgba(16, 185, 129, 0.15)', color: '#34d399' }
      : { text: catalogBadge || 'Codex', bg: '#d1fae5', color: '#047857' };
  }
  if (isClaudeModel(modelName)) {
    return isDark
      ? { text: catalogBadge || 'Claude', bg: 'rgba(139, 92, 246, 0.15)', color: '#a78bfa' }
      : { text: catalogBadge || 'Claude', bg: '#f3e8ff', color: '#7c3aed' };
  }
  if (name.includes('flash')) {
    return isDark
      ? { text: 'Flash', bg: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24' }
      : { text: 'Flash', bg: '#fef3c7', color: '#d97706' };
  }
  if (name.includes('pro')) {
    return isDark
      ? { text: 'Pro', bg: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa' }
      : { text: 'Pro', bg: '#dbeafe', color: '#2563eb' };
  }
  if (name.includes('claude')) {
    return isDark
      ? { text: 'Claude', bg: 'rgba(139, 92, 246, 0.15)', color: '#a78bfa' }
      : { text: 'Claude', bg: '#f3e8ff', color: '#7c3aed' };
  }
  if (name.includes('gpt')) {
    return isDark
      ? { text: 'GPT', bg: 'rgba(16, 185, 129, 0.15)', color: '#34d399' }
      : { text: 'GPT', bg: '#ecfdf5', color: '#059669' };
  }
  if (name.includes('kimi')) {
    return isDark
      ? { text: catalogBadge || 'Kimi', bg: 'rgba(6, 182, 212, 0.15)', color: '#22d3ee' }
      : { text: catalogBadge || 'Kimi', bg: '#cffafe', color: '#0e7490' };
  }
  return isDark
    ? { text: catalogBadge || 'AI', bg: 'rgba(107, 114, 128, 0.15)', color: '#9ca3af' }
    : { text: catalogBadge || 'AI', bg: '#e5e7eb', color: '#4b5563' };
};

const getMediaType = (url: string) => {
  if (url.includes('type=image')) return 'image';
  if (url.includes('type=video')) return 'video';
  if (url.includes('type=audio')) return 'audio';
  if (url.includes('type=document')) return 'document';

  // Parse path parameter if it exists to extract correct extension
  let targetUrl = url;
  if (url.includes('path=')) {
    const match = url.match(/[?&]path=([^&]+)/);
    if (match && match[1]) {
      targetUrl = decodeURIComponent(match[1]);
    }
  }

  const ext = targetUrl.split('.').pop()?.split('?')[0]?.split('&')[0]?.toLowerCase();
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'heic'].includes(ext || '')) {
    return 'image';
  }
  if (['mp4', 'mov', 'm4v', '3gp', 'avi', 'mkv'].includes(ext || '')) {
    return 'video';
  }
  if (['mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac'].includes(ext || '')) {
    return 'audio';
  }
  return 'document';
};

const VideoPlayerView = ({ url }: { url: string }) => {
  const filename = url.split('/').pop()?.split('?')[0] || 'video';
  const cleanName = filename.replace('media__', '');
  return (
    <TouchableOpacity 
      style={styles.videoContainer} 
      onPress={() => Linking.openURL(url)}
      activeOpacity={0.8}
    >
      <View style={styles.videoPlaceholder}>
        <Text style={styles.playIcon}>▶</Text>
        <Text style={styles.videoText} numberOfLines={1}>{cleanName}</Text>
      </View>
    </TouchableOpacity>
  );
};

const AudioPlayerView = ({ url, theme }: { url: string, theme: any }) => {
  const [sound, setSound] = useState<Audio.Sound | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    return () => {
      if (sound) {
        sound.unloadAsync();
      }
    };
  }, [sound]);

  const handlePlayPause = async () => {
    if (sound) {
      if (isPlaying) {
        await sound.pauseAsync();
        setIsPlaying(false);
      } else {
        await sound.playAsync();
        setIsPlaying(true);
      }
    } else {
      try {
        const { sound: newSound } = await Audio.Sound.createAsync(
          { uri: url },
          { shouldPlay: true },
          onPlaybackStatusUpdate
        );
        setSound(newSound);
        setIsPlaying(true);
      } catch (err) {
        Alert.alert("Error", "Could not play audio.");
      }
    }
  };

  const onPlaybackStatusUpdate = (status: any) => {
    if (status.isLoaded) {
      setPosition(status.positionMillis);
      setDuration(status.durationMillis || 0);
      if (status.didJustFinish) {
        setIsPlaying(false);
        setPosition(0);
      }
    }
  };

  const formatTime = (millis: number) => {
    const totalSecs = Math.floor(millis / 1000);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  };

  const progress = duration > 0 ? position / duration : 0;

  return (
    <View style={[styles.audioPlayer, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
      <TouchableOpacity onPress={handlePlayPause} style={styles.audioPlayButton}>
        <Text style={{ color: theme.accent, fontSize: 18 }}>{isPlaying ? '⏸' : '▶'}</Text>
      </TouchableOpacity>
      <View style={styles.audioInfo}>
        <Text style={[styles.audioTitle, { color: theme.textPrimary }]}>Voice Recording</Text>
        <View style={styles.progressBarBg}>
          <View style={[styles.progressBarFill, { width: `${progress * 100}%`, backgroundColor: theme.accent }]} />
        </View>
        <Text style={[styles.audioTime, { color: theme.textSecondary }]}>
          {formatTime(position)} / {formatTime(duration)}
        </Text>
      </View>
    </View>
  );
};

const DocumentAttachmentView = ({ url, filename, theme }: { url: string, filename: string, theme: any }) => {
  return (
    <TouchableOpacity 
      style={[styles.documentContainer, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]} 
      onPress={() => Linking.openURL(url)}
      activeOpacity={0.8}
    >
      <Text style={styles.documentIcon}>📄</Text>
      <View style={{ flex: 1 }}>
        <Text style={[styles.documentName, { color: theme.textPrimary }]} numberOfLines={1}>{filename}</Text>
        <Text style={[styles.documentActionText, { color: theme.accent }]}>Tap to open / download</Text>
      </View>
    </TouchableOpacity>
  );
};

function QuestionCard({
  question,
  disabled,
  theme,
  isDark,
  onSubmit,
}: {
  question: QuestionPayload;
  disabled: boolean;
  theme: typeof colors.light;
  isDark: boolean;
  onSubmit: (answer: string) => void;
}) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [otherText, setOtherText] = useState('');
  const otherIndex = question.options.length;

  const selectedAnswer = selectedIndex === otherIndex
    ? otherText.trim()
    : selectedIndex !== null
      ? question.options[selectedIndex]
      : '';

  const handleSubmit = () => {
    if (disabled) return;
    if (!selectedAnswer.trim()) {
      Alert.alert("Choose an answer", "Please select an option or write an answer.");
      return;
    }
    onSubmit(selectedAnswer);
  };

  const renderOption = (option: string, index: number) => {
    const selected = selectedIndex === index;
    return (
      <TouchableOpacity
        key={`${index}-${option}`}
        activeOpacity={0.8}
        disabled={disabled}
        style={[
          styles.questionOptionRow,
          { backgroundColor: theme.bgSecondary, borderColor: selected ? theme.accent : theme.borderColor },
          selected && { backgroundColor: isDark ? 'rgba(59, 130, 246, 0.14)' : 'rgba(37, 99, 235, 0.06)' },
        ]}
        onPress={() => setSelectedIndex(index)}
      >
        <View style={[styles.questionOptionNum, { backgroundColor: selected ? theme.accent : theme.bgActive }]}>
          <Text style={[styles.questionOptionNumText, { color: selected ? '#ffffff' : theme.textSecondary }]}>{index + 1}</Text>
        </View>
        <Text style={[styles.questionOptionText, { color: theme.textPrimary }]}>{option}</Text>
      </TouchableOpacity>
    );
  };

  return (
    <View
      style={[
        styles.questionCardContainer,
        { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor },
        disabled && styles.questionCardDisabled,
      ]}
    >
      <Text style={[styles.questionTitleText, { color: theme.textPrimary }]}>{question.question}</Text>

      {question.options.map(renderOption)}

      {question.allow_other && (
        <TouchableOpacity
          activeOpacity={0.8}
          disabled={disabled}
          style={[
            styles.questionOptionRow,
            { backgroundColor: theme.bgSecondary, borderColor: selectedIndex === otherIndex ? theme.accent : theme.borderColor },
            selectedIndex === otherIndex && { backgroundColor: isDark ? 'rgba(59, 130, 246, 0.14)' : 'rgba(37, 99, 235, 0.06)' },
          ]}
          onPress={() => setSelectedIndex(otherIndex)}
        >
          <View style={[styles.questionOptionNum, { backgroundColor: selectedIndex === otherIndex ? theme.accent : theme.bgActive }]}>
            <Text style={[styles.questionOptionNumText, { color: selectedIndex === otherIndex ? '#ffffff' : theme.textSecondary }]}>
              {otherIndex + 1}
            </Text>
          </View>
          <Text style={[styles.questionOtherLabel, { color: theme.textPrimary }]}>Other:</Text>
          <TextInput
            editable={!disabled}
            style={[styles.questionOtherInput, { color: theme.textPrimary, borderBottomColor: selectedIndex === otherIndex ? theme.accent : theme.borderColor }]}
            placeholder="Write your answer..."
            placeholderTextColor={theme.textMuted}
            value={otherText}
            onFocus={() => setSelectedIndex(otherIndex)}
            onChangeText={(value) => {
              setOtherText(value);
              setSelectedIndex(otherIndex);
            }}
          />
        </TouchableOpacity>
      )}

      {!disabled && (
        <View style={styles.questionActionsRow}>
          <TouchableOpacity style={styles.questionSkipBtn} onPress={() => onSubmit("Skip")}>
            <Text style={[styles.questionSkipText, { color: theme.textSecondary }]}>Skip</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.questionSubmitBtn, { backgroundColor: theme.accent }]} onPress={handleSubmit}>
            <Text style={styles.questionSubmitText}>Submit ↵</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

interface MessageSegment {
  type: 'text' | 'details';
  summary?: string;
  body?: string;
  text?: string;
}

const parseMessageSegments = (content: string): MessageSegment[] => {
  const segments: MessageSegment[] = [];
  let remaining = content;
  
  while (remaining.length > 0) {
    const detailsStartIdx = remaining.indexOf('<details>');
    if (detailsStartIdx === -1) {
      segments.push({ type: 'text', text: remaining });
      break;
    }
    
    if (detailsStartIdx > 0) {
      segments.push({ type: 'text', text: remaining.substring(0, detailsStartIdx) });
    }
    
    const detailsEndIdx = remaining.indexOf('</details>', detailsStartIdx);
    if (detailsEndIdx === -1) {
      segments.push({ type: 'text', text: remaining.substring(detailsStartIdx) });
      break;
    }
    
    const detailsBlock = remaining.substring(detailsStartIdx + 9, detailsEndIdx);
    let summaryText = 'Details';
    let bodyText = detailsBlock;
    
    const summaryStartIdx = detailsBlock.indexOf('<summary>');
    const summaryEndIdx = detailsBlock.indexOf('</summary>');
    if (summaryStartIdx !== -1 && summaryEndIdx !== -1 && summaryEndIdx > summaryStartIdx) {
      summaryText = detailsBlock.substring(summaryStartIdx + 9, summaryEndIdx);
      bodyText = detailsBlock.substring(0, summaryStartIdx) + detailsBlock.substring(summaryEndIdx + 10);
    }
    
    segments.push({
      type: 'details',
      summary: summaryText.trim(),
      body: bodyText.trim()
    });
    
    remaining = remaining.substring(detailsEndIdx + 10);
  }
  
  return segments;
};

const CollapsibleDetailsCard = ({ summary, body, theme, fontSize = 14 }: { summary: string; body: string; theme: any; fontSize?: number }) => {
  const [expanded, setExpanded] = useState(false);
  
  return (
    <View style={[styles.collapsibleCard, { borderColor: theme.borderColor }]}>
      <TouchableOpacity 
        style={[styles.collapsibleHeader, { backgroundColor: theme.bgSecondary }]} 
        onPress={() => setExpanded(!expanded)}
      >
        <Text style={[styles.collapsibleTitle, { color: theme.textPrimary }]}>
          {summary}
        </Text>
        <Text style={{ color: theme.textSecondary, fontSize: 12 }}>
          {expanded ? '▼' : '►'}
        </Text>
      </TouchableOpacity>
      
      {expanded && (
        <View style={[styles.collapsibleBody, { backgroundColor: theme.bgActive }]}>
          <Text style={[styles.collapsibleBodyText, { color: theme.textPrimary, fontSize: fontSize - 2, lineHeight: (fontSize - 2) * 1.4 }]}>
            {body}
          </Text>
        </View>
      )}
    </View>
  );
};

const FontSizeSlider = ({
  value,
  onChange,
  theme,
}: {
  value: number;
  onChange: (val: number) => void;
  theme: any;
}) => {
  const min = 10;
  const max = 22;
  const trackWidth = 250;

  const handleTouch = (evt: any) => {
    const touchX = evt.nativeEvent.locationX;
    const ratio = Math.max(0, Math.min(1, touchX / trackWidth));
    const calculatedValue = Math.round(min + ratio * (max - min));
    onChange(calculatedValue);
  };

  const percentage = ((value - min) / (max - min)) * 100;

  return (
    <View style={styles.customSliderContainer}>
      <Text style={[styles.customSliderValueText, { color: theme.textPrimary }]}>
        {value}px
      </Text>
      <View
        style={[styles.customSliderTrack, { width: trackWidth, backgroundColor: theme.borderColor }]}
        onStartShouldSetResponder={() => true}
        onResponderGrant={handleTouch}
        onResponderMove={handleTouch}
      >
        <View
          style={[
            styles.customSliderActiveTrack,
            {
              width: `${percentage}%`,
              backgroundColor: theme.accent,
            },
          ]}
        />
        <View
          style={[
            styles.customSliderKnob,
            {
              left: `${percentage}%`,
              backgroundColor: '#ffffff',
              borderColor: theme.accent,
            },
          ]}
        />
      </View>
      <View style={[styles.customSliderLabels, { width: trackWidth }]}>
        <Text style={[styles.customSliderLabelText, { color: theme.textMuted }]}>{min}px</Text>
        <Text style={[styles.customSliderLabelText, { color: theme.textMuted }]}>{max}px</Text>
      </View>
    </View>
  );
};

export default function ChatScreen({ onDisconnect }: ChatScreenProps) {
  const scheme = useColorScheme();
  const insets = useSafeAreaInsets();
  const [isKeyboardVisible, setIsKeyboardVisible] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);
  const promptBottomPadding = Platform.OS === 'android'
    ? isKeyboardVisible
      ? 6
      : Math.max(insets.bottom, 12)
    : insets.bottom + 10;
  const promptKeyboardOffset = Platform.OS === 'android' && isKeyboardVisible ? keyboardHeight : 0;

  const [messages, setMessages] = useState<Message[]>([]);
  const [localAttachments, setLocalAttachments] = useState<{ id: string; uri: string; name: string; type: 'image' | 'video' | 'document' | 'audio' }[]>([]);
  const [inputText, setInputText] = useState('');

  const addLocalAttachment = (uri: string, name: string, type: 'image' | 'video' | 'document' | 'audio') => {
    if (localAttachments.length >= 5) {
      Alert.alert("Limit Reached", "You can attach a maximum of 5 files.");
      return;
    }
    setLocalAttachments(current => [
      ...current,
      {
        id: `local_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
        uri,
        name,
        type
      }
    ]);
    showToast(`${type.charAt(0).toUpperCase() + type.slice(1)} attached`);
  };

  const removeLocalAttachment = (id: string) => {
    setLocalAttachments(current => current.filter(item => item.id !== id));
  };
const [loading, setLoading] = useState(false);
const [taskProgressEvents, setTaskProgressEvents] = useState<ChatTaskEvent[]>([]);
const [activeConvoId, setActiveConvoId] = useState<string>('');
const [activeConvoProject, setActiveConvoProject] = useState<string>('agy');
const [activeConvoProvider, setActiveConvoProvider] = useState<AgentProvider>('agy');
const [conversations, setConversations] = useState<Conversation[]>([]);
  const [queuedPrompts, setQueuedPrompts] = useState<QueuedPrompt[]>([]);
  const [isInitializingChat, setIsInitializingChat] = useState(true);
  const [loadingConvList, setLoadingConvList] = useState(false);

  // Toast notification state
  const [toastMessage, setToastMessage] = useState('');
  const [toastVisible, setToastVisible] = useState(false);
  const toastOpacity = useRef(new Animated.Value(0)).current;
  const toastTranslateY = useRef(new Animated.Value(20)).current;
  const toastTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isVoiceRecording, setIsVoiceRecording] = useState(false);
  const lastVoiceTranscriptRef = useRef('');
  const voiceWaveAnim = useRef(new Animated.Value(0)).current;

// Model, Target & Project Pickers
const [modelsList, setModelsList] = useState<ModelOption[]>(FALLBACK_MODELS);
const [modelCatalogVersion, setModelCatalogVersion] = useState('built-in');
const [selectedModel, setSelectedModel] = useState("Gemini 3.5 Flash (High)");
const [selectedCodexEffort, setSelectedCodexEffort] = useState<CodexEffort>("Medium");
const [selectedCodexSpeed, setSelectedCodexSpeed] = useState<CodexSpeed>("Standard");
const [selectedClaudeEffort, setSelectedClaudeEffort] = useState<ClaudeEffort>("Medium");
const [selectedClaudeThinking, setSelectedClaudeThinking] = useState(true);
const [selectedTarget, setSelectedTarget] = useState(DEFAULT_EXECUTION_TARGET);
const [selectedSpeechLang, setSelectedSpeechLang] = useState("th-TH");
const [selectedThemeMode, setSelectedThemeMode] = useState<ThemeMode>("system");
const [selectedFontSize, setSelectedFontSize] = useState<number>(14);
const [selectedProject, setSelectedProject] = useState("agy");
const [projects, setProjects] = useState<string[]>(["agy"]);
const [loadingProjects, setLoadingProjects] = useState(false);
const [expandedProjects, setExpandedProjects] = useState<{ [key: string]: boolean }>({});

const chatFadeAnim = useRef(new Animated.Value(1)).current;
const chatTranslateY = useRef(new Animated.Value(0)).current;

const animateChatTransition = () => {
  chatFadeAnim.setValue(0);
  chatTranslateY.setValue(15);
  Animated.parallel([
    Animated.timing(chatFadeAnim, {
      toValue: 1,
      duration: 350,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }),
    Animated.timing(chatTranslateY, {
      toValue: 0,
      duration: 350,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }),
  ]).start();
};

const toggleThemeMode = async () => {
  const nextMode = effectiveScheme === 'light' ? 'dark' : 'light';
  setSelectedThemeMode(nextMode);
  setDraftSettingsThemeMode(nextMode);
  try {
    await SecureStore.setItemAsync(PREFERENCE_KEYS.themeMode, nextMode);
    showToast(`Switched to ${nextMode} theme`);
  } catch (err) {
    console.error("Error saving toggled theme:", err);
  }
};


// Modal Overlays
const [isModelModalOpen, setIsModelModalOpen] = useState(false);
const [isEffortModalOpen, setIsEffortModalOpen] = useState(false);
const [isSpeedModalOpen, setIsSpeedModalOpen] = useState(false);
const [isTargetModalOpen, setIsTargetModalOpen] = useState(false);
const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
const [isPlusModalOpen, setIsPlusModalOpen] = useState(false);
const [isUsageModalOpen, setIsUsageModalOpen] = useState(false);
const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
const [settingsTab, setSettingsTab] = useState<SettingsTab>('general');
const [draftSettingsModel, setDraftSettingsModel] = useState(selectedModel);
const [draftSettingsCodexEffort, setDraftSettingsCodexEffort] = useState<CodexEffort>(selectedCodexEffort);
const [draftSettingsCodexSpeed, setDraftSettingsCodexSpeed] = useState<CodexSpeed>(selectedCodexSpeed);
const [draftSettingsClaudeEffort, setDraftSettingsClaudeEffort] = useState<ClaudeEffort>(selectedClaudeEffort);
const [draftSettingsClaudeThinking, setDraftSettingsClaudeThinking] = useState(selectedClaudeThinking);
const [draftSettingsTarget, setDraftSettingsTarget] = useState(selectedTarget);
const [draftSettingsSpeechLang, setDraftSettingsSpeechLang] = useState(selectedSpeechLang);
const [draftSettingsThemeMode, setDraftSettingsThemeMode] = useState<ThemeMode>(selectedThemeMode);
const [draftSettingsFontSize, setDraftSettingsFontSize] = useState<number>(selectedFontSize);
const [uploadingMedia, setUploadingMedia] = useState(false);
const [hostBaseUrl, setHostBaseUrl] = useState<string>('');
const [authToken, setAuthToken] = useState<string>('');
const [audioRecording, setAudioRecording] = useState<Audio.Recording | null>(null);
const [isRecordingAudio, setIsRecordingAudio] = useState(false);
  const [usageLimitData, setUsageLimitData] = useState<any>(DEFAULT_USAGE_LIMIT_DATA);
  const [usageMode, setUsageMode] = useState<'usage' | 'remaining'>('usage');
  const [loadingUsage, setLoadingUsage] = useState(false);
  const [usageLimitError, setUsageLimitError] = useState('');
  const [isConnected, setIsConnected] = useState(true);

  const scrollViewRef = useRef<ScrollView>(null);
  const promptInputRef = useRef<TextInput>(null);
  const inputSelectionRef = useRef({ start: 0, end: 0 });
  const [inputSelection, setInputSelection] = useState({ start: 0, end: 0 });
  const messagesRef = useRef<Message[]>([]);
  const loadingRef = useRef(false);
  const activeConvoIdRef = useRef('');
  const activeConvoProjectRef = useRef('agy');
  const activeConvoProviderRef = useRef<AgentProvider>('agy');
  const selectedProjectRef = useRef('agy');
  const queuedPromptsRef = useRef<QueuedPrompt[]>([]);
  const pendingConversationScrollRef = useRef(false);
  const usageLimitControllerRef = useRef<AbortController | null>(null);

  // Sidebar expand/collapse state & animation
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const sidebarAnim = useRef(new Animated.Value(-280)).current; // Sidebar width is 280
  const sidebarOpacity = useRef(new Animated.Value(0)).current;
  const backdropOpacity = useRef(new Animated.Value(0)).current;
  const effectiveScheme = selectedThemeMode === 'system' ? scheme : selectedThemeMode;
  const theme = effectiveScheme === 'light' ? colors.light : colors.dark;
  const isDark = effectiveScheme === 'dark';
  const connectionStatusColor = isConnected ? theme.statusGreen : theme.statusRed;

const updateMessages = (nextMessages: Message[]) => {
messagesRef.current = nextMessages;
setMessages(nextMessages);
};

const setLoadingState = (nextLoading: boolean) => {
loadingRef.current = nextLoading;
setLoading(nextLoading);
};

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

const getEventIconAndCleanMessage = (message: string) => {
  const lower = message.toLowerCase();
  let icon = '⚙️';
  let cleanMessage = message;

  if (lower.includes('thinking') || lower.includes('planning') || lower.includes('brainstorming')) {
    icon = '💭';
  } else if (lower.includes('read_file') || lower.includes('reading') || lower.includes('view_file')) {
    icon = '📄';
  } else if (lower.includes('write_file') || lower.includes('writing') || lower.includes('editing') || lower.includes('replace_file')) {
    icon = '✏️';
  } else if (lower.includes('tool') || lower.includes('executing')) {
    icon = '🛠️';
  } else if (lower.includes('command') || lower.includes('running') || lower.includes('executing command')) {
    icon = '💻';
  } else if (lower.includes('complete') || lower.includes('finished') || lower.includes('done')) {
    icon = '✓';
  }

  cleanMessage = message.replace(/^(progress|error):\s*/i, '').trim();
  return { icon, cleanMessage };
};

const setPromptCursor = (cursor: number) => {
const nextSelection = { start: cursor, end: cursor };
inputSelectionRef.current = nextSelection;
setInputSelection(nextSelection);

requestAnimationFrame(() => {
promptInputRef.current?.focus();
(promptInputRef.current as any)?.setNativeProps?.({ selection: nextSelection });
});
};

const scrollMessagesToBottom = (animated = true) => {
requestAnimationFrame(() => {
scrollViewRef.current?.scrollToEnd({ animated });
});
};

const isConnectionError = (err: unknown) => {
const message = err instanceof Error ? err.message : String(err);
return /Cannot reach host|No paired connection|Network request failed|Failed to fetch|aborted|401/.test(message);
};

const callHostApi = async (endpoint: string, options: RequestInit = {}) => {
try {
const data = await apiCall(endpoint, options);
setIsConnected(true);
const conn = await loadConnection();
if (conn) {
const currentUrl = await getActiveBaseUrl(conn);
if (currentUrl && currentUrl !== hostBaseUrl) {
setHostBaseUrl(currentUrl);
}
}
return data;
} catch (err) {
setIsConnected(!isConnectionError(err));
throw err;
}
};

const updateActiveConversation = (
conversationId: string,
project: string,
provider: AgentProvider = activeConvoProviderRef.current,
) => {
activeConvoIdRef.current = conversationId;
activeConvoProjectRef.current = project;
activeConvoProviderRef.current = provider;
selectedProjectRef.current = project;
setActiveConvoId(conversationId);
setActiveConvoProject(project);
setActiveConvoProvider(provider);
setSelectedProject(project);
};

const setQueuedPromptList = (nextQueue: QueuedPrompt[]) => {
queuedPromptsRef.current = nextQueue;
setQueuedPrompts(nextQueue);
};

const applySelectedModel = (modelName: string) => {
const nextModel = getModelOption(modelName);
if (!nextModel) return;
const currentProvider = getModelOption(selectedModel)?.provider || 'agy';

if (!nextModel.supportsUltra && selectedCodexEffort === 'Ultra') {
setSelectedCodexEffort('Medium');
}
if (!nextModel.supportsFast && selectedCodexSpeed === 'Fast') {
setSelectedCodexSpeed('Standard');
}
if (!nextModel.supportsClaudeExtra && selectedClaudeEffort === 'Extra') {
setSelectedClaudeEffort('High');
}
if (nextModel.thinkingRequired) {
setSelectedClaudeThinking(true);
}

if (currentProvider !== nextModel.provider && activeConvoIdRef.current) {
  activeConvoProviderRef.current = nextModel.provider;
  setActiveConvoProvider(nextModel.provider);
}

setSelectedModel(modelName);
};

const applyModelCatalog = (catalog: ModelCatalog) => {
  const nextModels = catalogToModelOptions(catalog);
  if (!nextModels.length) return;
  activeModelsList = nextModels;
  activeDefaultModel = nextModels.some((model) => model.value === catalog.default_model)
    ? catalog.default_model
    : nextModels[0].value;
  setModelsList(nextModels);
  setModelCatalogVersion(catalog.catalog_version);
  if (!nextModels.some((model) => model.value === selectedModel)) {
    setSelectedModel(activeDefaultModel);
    setDraftSettingsModel(activeDefaultModel);
  }
};

const refreshModelCatalog = async () => {
  try {
    const freshCatalog = await apiCall('/api/models');
    if (!isModelCatalog(freshCatalog)) {
      throw new Error('Host returned an invalid model catalog');
    }
    applyModelCatalog(freshCatalog);
    await writeCachedModelCatalog(freshCatalog);
    return true;
  } catch (catalogError) {
    console.warn("Using cached or built-in model catalog:", catalogError);
    return false;
  }
};

useEffect(() => {
messagesRef.current = messages;
}, [messages]);

useEffect(() => {
loadingRef.current = loading;
}, [loading]);

useEffect(() => {
activeConvoIdRef.current = activeConvoId;
animateChatTransition();
}, [activeConvoId]);

useEffect(() => {
activeConvoProjectRef.current = activeConvoProject;
}, [activeConvoProject]);

useEffect(() => {
activeConvoProviderRef.current = activeConvoProvider;
}, [activeConvoProvider]);

useEffect(() => {
selectedProjectRef.current = selectedProject;
}, [selectedProject]);

  const loadSavedPreferences = async () => {
    try {
      const [
        savedModel,
        savedTarget,
        savedSpeechLang,
        savedThemeMode,
        savedFontSize,
        savedCodexEffort,
        savedCodexSpeed,
        savedClaudeEffort,
        savedClaudeThinking,
      ] = await Promise.all([
        SecureStore.getItemAsync(PREFERENCE_KEYS.model),
        SecureStore.getItemAsync(PREFERENCE_KEYS.target),
        SecureStore.getItemAsync(PREFERENCE_KEYS.speechLang),
        SecureStore.getItemAsync(PREFERENCE_KEYS.themeMode),
        SecureStore.getItemAsync(PREFERENCE_KEYS.fontSize),
        SecureStore.getItemAsync(PREFERENCE_KEYS.codexEffort),
        SecureStore.getItemAsync(PREFERENCE_KEYS.codexSpeed),
        SecureStore.getItemAsync(PREFERENCE_KEYS.claudeEffort),
        SecureStore.getItemAsync(PREFERENCE_KEYS.claudeThinking),
      ]);

      const effectiveModel = savedModel && activeModelsList.some((model) => model.value === savedModel)
        ? savedModel
        : activeDefaultModel;
      if (savedModel && activeModelsList.some((model) => model.value === savedModel)) {
        setSelectedModel(savedModel);
      } else {
        setSelectedModel(effectiveModel);
      }
      if (
        savedCodexEffort
        && getCodexEfforts(effectiveModel).some((item) => item.value === savedCodexEffort)
      ) {
        setSelectedCodexEffort(savedCodexEffort as CodexEffort);
      }
      if (
        savedCodexSpeed
        && getCodexSpeeds(effectiveModel).some((item) => item.value === savedCodexSpeed)
      ) {
        setSelectedCodexSpeed(savedCodexSpeed as CodexSpeed);
      }
      if (
        savedClaudeEffort
        && getClaudeEfforts(effectiveModel).some((item) => item.value === savedClaudeEffort)
      ) {
        setSelectedClaudeEffort(savedClaudeEffort as ClaudeEffort);
      }
      if (savedClaudeThinking === 'true' || savedClaudeThinking === 'false') {
        setSelectedClaudeThinking(savedClaudeThinking === 'true');
      }
      if (savedTarget && targetsList.some((target) => target.value === savedTarget)) {
        setSelectedTarget(savedTarget);
      }
      if (savedSpeechLang && speechLanguageList.some((language) => language.value === savedSpeechLang)) {
        setSelectedSpeechLang(savedSpeechLang);
      }
      if (savedThemeMode && themeModeList.some((mode) => mode.value === savedThemeMode)) {
        setSelectedThemeMode(savedThemeMode as ThemeMode);
      }
      if (savedFontSize) {
        const size = parseInt(savedFontSize, 10);
        if (!isNaN(size) && size >= 10 && size <= 22) {
          setSelectedFontSize(size);
        }
      }
    } catch (err) {
      console.error("Error loading saved settings:", err);
    }
  };

  useEffect(() => {
    let isMounted = true;

    const initializeChat = async () => {
      setIsInitializingChat(true);
      try {
        const cachedCatalog = await readCachedModelCatalog();
        if (cachedCatalog && isMounted) {
          applyModelCatalog(cachedCatalog);
        }
        if (isMounted) {
          await refreshModelCatalog();
        }
        await loadSavedPreferences();
        const conn = await loadConnection();
        if (conn) {
          const url = await getActiveBaseUrl(conn);
          if (url && isMounted) {
            setHostBaseUrl(url);
          }
          if (conn.token && isMounted) {
            setAuthToken(conn.token);
          }
        }
        await loadProjects();
        await loadConversations();
        fetchUsageLimits();
      } finally {
        if (isMounted) {
          setIsInitializingChat(false);
        }
      }
    };

    initializeChat();

    return () => {
      isMounted = false;
      usageLimitControllerRef.current?.abort();
      if (toastTimeoutRef.current) {
        clearTimeout(toastTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      if (isConnected) {
        refreshModelCatalog();
      }
    }, 10 * 60 * 1000);
    return () => clearInterval(interval);
  }, [isConnected]);

  useEffect(() => {
    const showSubscription = Keyboard.addListener('keyboardDidShow', (event) => {
      setIsKeyboardVisible(true);
      setKeyboardHeight(event.endCoordinates?.height ?? 0);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setIsKeyboardVisible(false);
      setKeyboardHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  // Periodic auto-reconnect effect when disconnected
  useEffect(() => {
    if (isConnected) return;

    const interval = setInterval(async () => {
      try {
        const conn = await loadConnection();
        if (conn && conn.token) {
          const baseUrl = await getActiveBaseUrl(conn, true); // forceRefresh IP/URL from registry
          if (baseUrl) {
            // Ping projects to confirm connection
            const response = await fetch(`${baseUrl}/api/projects`, {
              headers: { 
                'Authorization': `Bearer ${conn.token}`,
                'Bypass-Tunnel-Reminder': 'true'
              }
            });
            if (response.status === 200) {
              console.log("Auto-reconnected successfully to base URL:", baseUrl);
              setIsConnected(true);
              // Reload projects and conversations list
              loadConversations(true);
              fetchUsageLimits();
              refreshModelCatalog();
            }
          }
        }
      } catch (err) {
        console.log("Auto-reconnect attempt failed:", err);
      }
    }, 10000); // Try every 10 seconds

    return () => clearInterval(interval);
  }, [isConnected]);

  const showToast = (message: string) => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }
    setToastMessage(message);
    setToastVisible(true);

    toastOpacity.setValue(0);
    toastTranslateY.setValue(20);

    Animated.parallel([
      Animated.timing(toastOpacity, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }),
      Animated.timing(toastTranslateY, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }),
    ]).start(() => {
      toastTimeoutRef.current = setTimeout(() => {
        Animated.parallel([
          Animated.timing(toastOpacity, {
            toValue: 0,
            duration: 200,
            useNativeDriver: true,
          }),
          Animated.timing(toastTranslateY, {
            toValue: -10,
            duration: 200,
            useNativeDriver: true,
          }),
        ]).start(({ finished }) => {
          if (finished) {
            setToastVisible(false);
          }
        });
      }, 1500);
    });
};

const openSettingsModal = () => {
setDraftSettingsModel(selectedModel);
setDraftSettingsCodexEffort(selectedCodexEffort);
setDraftSettingsCodexSpeed(selectedCodexSpeed);
setDraftSettingsClaudeEffort(selectedClaudeEffort);
setDraftSettingsClaudeThinking(selectedClaudeThinking);
setDraftSettingsTarget(selectedTarget);
setDraftSettingsSpeechLang(selectedSpeechLang);
setDraftSettingsThemeMode(selectedThemeMode);
setDraftSettingsFontSize(selectedFontSize);
setSettingsTab('general');
setIsSettingsModalOpen(true);
};

const saveSettings = async () => {
applySelectedModel(draftSettingsModel);
const draftModelOption = getModelOption(draftSettingsModel);
const nextEffort = draftModelOption?.supportsUltra || draftSettingsCodexEffort !== 'Ultra'
  ? draftSettingsCodexEffort
  : 'Medium';
const nextSpeed = draftModelOption?.supportsFast || draftSettingsCodexSpeed !== 'Fast'
  ? draftSettingsCodexSpeed
  : 'Standard';
const nextClaudeEffort = draftModelOption?.supportsClaudeExtra || draftSettingsClaudeEffort !== 'Extra'
  ? draftSettingsClaudeEffort
  : 'High';
const nextClaudeThinking = draftModelOption?.thinkingRequired ? true : draftSettingsClaudeThinking;
setSelectedCodexEffort(nextEffort);
setSelectedCodexSpeed(nextSpeed);
setSelectedClaudeEffort(nextClaudeEffort);
setSelectedClaudeThinking(nextClaudeThinking);
setSelectedTarget(draftSettingsTarget);
setSelectedSpeechLang(draftSettingsSpeechLang);
setSelectedThemeMode(draftSettingsThemeMode);
setSelectedFontSize(draftSettingsFontSize);

try {
await Promise.all([
SecureStore.setItemAsync(PREFERENCE_KEYS.model, draftSettingsModel),
SecureStore.setItemAsync(PREFERENCE_KEYS.codexEffort, nextEffort),
SecureStore.setItemAsync(PREFERENCE_KEYS.codexSpeed, nextSpeed),
SecureStore.setItemAsync(PREFERENCE_KEYS.claudeEffort, nextClaudeEffort),
SecureStore.setItemAsync(PREFERENCE_KEYS.claudeThinking, String(nextClaudeThinking)),
SecureStore.setItemAsync(PREFERENCE_KEYS.target, draftSettingsTarget),
SecureStore.setItemAsync(PREFERENCE_KEYS.speechLang, draftSettingsSpeechLang),
SecureStore.setItemAsync(PREFERENCE_KEYS.themeMode, draftSettingsThemeMode),
SecureStore.setItemAsync(PREFERENCE_KEYS.fontSize, String(draftSettingsFontSize)),
]);
showToast("Settings saved");
} catch (err) {
console.error("Error saving settings:", err);
Alert.alert("Settings", "Could not save settings on this device.");
}

setIsSettingsModalOpen(false);
fetchUsageLimits();
};

const loadProjects = async () => {
setLoadingProjects(true);
try {
const data = await callHostApi('/api/projects');
const list = Array.isArray(data.projects) && data.projects.length > 0 ? data.projects : ["agy"];
setProjects(list);
if (!list.includes(selectedProject)) {
setSelectedProject(list[0]);
selectedProjectRef.current = list[0];
}
} catch (err) {
console.error("Error loading projects:", err);
} finally {
setLoadingProjects(false);
}
};

  useEffect(() => {
    const speechModule = getSpeechRecognitionModule();
    if (!speechModule) return;

    const subscriptions = [
      speechModule.addListener("start", () => {
        lastVoiceTranscriptRef.current = '';
        setIsVoiceRecording(true);
      }),
      speechModule.addListener("end", () => {
        setIsVoiceRecording(false);
      }),
      speechModule.addListener("result", (event: any) => {
        if (event.isFinal === false) return;

        const transcript = event.results?.[0]?.transcript?.trim();
        if (!transcript || transcript === lastVoiceTranscriptRef.current) return;

        lastVoiceTranscriptRef.current = transcript;
        setInputText((current) => {
          const start = Math.max(0, Math.min(inputSelectionRef.current.start, current.length));
          const end = Math.max(start, Math.min(inputSelectionRef.current.end, current.length));
          const prefix = current.substring(0, start);
          const suffix = current.substring(end);
          const needsLeadingSpace = prefix.length > 0 && !/\s$/.test(prefix);
          const needsTrailingSpace = suffix.length > 0 && !/^\s/.test(suffix);
          const insertedText = `${needsLeadingSpace ? ' ' : ''}${transcript}${needsTrailingSpace ? ' ' : ''}`;
          const nextCursor = start + insertedText.length;
          const nextText = prefix + insertedText + suffix;

          setPromptCursor(nextCursor);

          return nextText;
        });
      }),
      speechModule.addListener("error", (event: any) => {
        setIsVoiceRecording(false);

        if (event.error === "aborted") return;
        if (event.error === "no-speech" || event.error === "speech-timeout") {
          showToast("No speech detected");
          return;
        }

        const message = event.message || "Speech recognition could not start on this device.";
        Alert.alert("Voice Input", message);
      }),
    ];

    return () => {
      subscriptions.forEach((subscription) => subscription.remove());
    };
  }, []);

  useEffect(() => {
    if (!isVoiceRecording) {
      voiceWaveAnim.stopAnimation();
      voiceWaveAnim.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.timing(voiceWaveAnim, {
        toValue: 1,
        duration: 900,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      })
    );
    loop.start();

    return () => loop.stop();
  }, [isVoiceRecording, voiceWaveAnim]);

  const renderVoiceListeningIndicator = () => {
    const rippleScale = voiceWaveAnim.interpolate({
      inputRange: [0, 1],
      outputRange: [1, 1.9],
    });
    const rippleOpacity = voiceWaveAnim.interpolate({
      inputRange: [0, 0.75, 1],
      outputRange: [0.35, 0.12, 0],
    });
    const barScales = [
      voiceWaveAnim.interpolate({ inputRange: [0, 0.5, 1], outputRange: [0.45, 1, 0.45] }),
      voiceWaveAnim.interpolate({ inputRange: [0, 0.25, 0.75, 1], outputRange: [0.75, 0.45, 1, 0.75] }),
      voiceWaveAnim.interpolate({ inputRange: [0, 0.5, 1], outputRange: [1, 0.45, 1] }),
    ];

    return (
      <>
        <Animated.View
          pointerEvents="none"
          style={[
            styles.voiceRipple,
            {
              backgroundColor: theme.accent,
              opacity: rippleOpacity,
              transform: [{ scale: rippleScale }],
            },
          ]}
        />
        <View style={styles.voiceWaveBars}>
          {barScales.map((scaleY, index) => (
            <Animated.View
              key={index}
              style={[
                styles.voiceWaveBar,
                {
                  backgroundColor: '#ffffff',
                  transform: [{ scaleY }],
                },
              ]}
            />
          ))}
        </View>
      </>
    );
  };

  const handleToggleVoiceInput = async () => {
    const speechModule = getSpeechRecognitionModule();

    if (!speechModule) {
      Alert.alert(
        "Voice Input",
        "Voice input needs a rebuilt development app. Run npm run android so the native speech module is installed."
      );
      return;
    }

    if (isVoiceRecording) {
      speechModule.stop();
      return;
    }

    try {
      if (typeof speechModule.isRecognitionAvailable === 'function' && !speechModule.isRecognitionAvailable()) {
        Alert.alert(
          "Voice Input",
          "Speech recognition is not available on this device. Please enable or install a speech recognition service."
        );
        return;
      }

      const permission = await speechModule.requestPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Microphone Permission", "Please allow microphone access to use voice input.");
        return;
      }

      speechModule.start({
        lang: selectedSpeechLang,
        interimResults: false,
        continuous: false,
        maxAlternatives: 1,
      });
    } catch (err: any) {
      setIsVoiceRecording(false);
      Alert.alert("Voice Input", err?.message || "Failed to start voice input.");
    }
  };

  const handleCopyMessage = async (content: string) => {
    try {
      let copied = false;

      try {
        // Safely check if native module exists before requiring expo-clipboard
        const { requireNativeModule } = require('expo-modules-core');
        if (requireNativeModule('ExpoClipboard')) {
          const ExpoClipboard = require('expo-clipboard');
          await ExpoClipboard.setStringAsync(content);
          copied = true;
        }
      } catch (err) {
        console.log("expo-clipboard native module not loaded, trying fallback:", err);
      }

      if (!copied) {
        // Fallback to deprecated react-native Clipboard
        const { Clipboard: RNClipboard } = require('react-native');
        if (RNClipboard && typeof RNClipboard.setString === 'function') {
          RNClipboard.setString(content);
          copied = true;
        }
      }

      if (copied) {
        showToast("Copied");
        Vibration.vibrate(35);
      } else {
        throw new Error("No clipboard module available. Please rebuild the app.");
      }
    } catch (err: any) {
      console.error("Failed to copy message:", err);
      Alert.alert(
        "Copy Failed",
        "Please rebuild the app using 'npm run android' or 'npm run ios' to enable native clipboard support."
      );
    }
  };

  const toggleSidebar = () => {
    if (isSidebarOpen) {
      Animated.parallel([
        Animated.timing(sidebarAnim, {
          toValue: -280,
          duration: 230,
          easing: Easing.in(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(sidebarOpacity, {
          toValue: 0,
          duration: 180,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(backdropOpacity, {
          toValue: 0,
          duration: 200,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
      ]).start(() => setIsSidebarOpen(false));
    } else {
      loadConversations(false);
      sidebarAnim.setValue(-280);
      sidebarOpacity.setValue(0);
      backdropOpacity.setValue(0);
      setIsSidebarOpen(true);
      Animated.parallel([
        Animated.timing(sidebarAnim, {
          toValue: 0,
          duration: 280,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(sidebarOpacity, {
          toValue: 1,
          duration: 220,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(backdropOpacity, {
          toValue: 1,
          duration: 260,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
      ]).start();
    }
  };

const loadConversations = async (autoSelect = true) => {
if (autoSelect) {
setLoadingConvList(true);
}
try {
const data = await callHostApi('/api/chat-history');
const list = data.conversations || [];
setConversations(list);

// Auto-select most recent conversation only on initial load.
if (autoSelect && list.length > 0 && !activeConvoId) {
await selectConversation(list[0].id, list[0].project);
}
    } catch (err) {
      console.error("Error loading conversations:", err);
} finally {
if (autoSelect) {
setLoadingConvList(false);
}
}
};

const selectConversation = async (cid: string, projectName?: string) => {
const selectedConversation = conversations.find((convo) => convo.id === cid);
const conversationProject = projectName || selectedConversation?.project;
const conversationProvider = selectedConversation?.provider
  || (
    cid.startsWith('codex_')
      ? 'codex'
      : cid.startsWith('claude_')
        ? 'claude'
        : cid.startsWith('kimi_')
          ? 'kimi'
          : 'agy'
  );
if (conversationProject) {
setSelectedProject(conversationProject);
selectedProjectRef.current = conversationProject;
updateActiveConversation(cid, conversationProject, conversationProvider);
} else {
activeConvoIdRef.current = cid;
setActiveConvoId(cid);
}
setQueuedPromptList([]);
setLoadingState(true);
    try {
const data = await callHostApi(`/api/conversation/${cid}`);
const resolvedProject = data.project || conversationProject;
const resolvedProvider: AgentProvider = ['codex', 'claude', 'kimi'].includes(data.provider)
  ? data.provider
  : conversationProvider;
if (resolvedProject) {
setSelectedProject(resolvedProject);
selectedProjectRef.current = resolvedProject;
updateActiveConversation(cid, resolvedProject, resolvedProvider);
}
if (data.model && getModelOption(data.model)) {
  setSelectedModel(data.model);
  if (data.effort) {
    if (getCodexEfforts(data.model).some((item) => item.value === data.effort)) {
      setSelectedCodexEffort(data.effort);
    }
    if (getClaudeEfforts(data.model).some((item) => item.value === data.effort)) {
      setSelectedClaudeEffort(data.effort);
    }
  }
  if (data.speed && getCodexSpeeds(data.model).some((item) => item.value === data.speed)) {
    setSelectedCodexSpeed(data.speed);
  }
  if (data.thinking !== undefined) {
    setSelectedClaudeThinking(data.thinking !== false);
  }
}
pendingConversationScrollRef.current = true;
updateMessages(data.messages || []);
      setTimeout(() => scrollMessagesToBottom(false), 250);
    } catch (err: any) {
      Alert.alert("Error", "Failed to load chat logs.");
    } finally {
      setLoadingState(false);
    }
  };

const startNewChat = () => {
const newId = `temp_${selectedProject}_${Math.random().toString(36).substring(2, 11)}`;
updateActiveConversation(newId, selectedProject, getModelOption(selectedModel)?.provider || 'agy');
setQueuedPromptList([]);
updateMessages([]);
};

const handleSelectProject = (project: string) => {
setSelectedProject(project);
selectedProjectRef.current = project;
activeConvoIdRef.current = '';
activeConvoProjectRef.current = project;
activeConvoProviderRef.current = getModelOption(selectedModel)?.provider || 'agy';
setActiveConvoId('');
setActiveConvoProject(project);
setActiveConvoProvider(activeConvoProviderRef.current);
setQueuedPromptList([]);
updateMessages([]);
setIsProjectModalOpen(false);
};

const ensureActiveConversationForContext = () => {
const conversationId = activeConvoId || `temp_${selectedProject}_${Math.random().toString(36).substring(2, 11)}`;
if (!activeConvoId) {
updateActiveConversation(conversationId, selectedProject, getModelOption(selectedModel)?.provider || 'agy');
}
return conversationId;
};

const insertPromptText = (textToInsert: string) => {
setIsPlusModalOpen(false);
setInputText((current) => {
const start = Math.max(0, Math.min(inputSelectionRef.current.start, current.length));
const end = Math.max(start, Math.min(inputSelectionRef.current.end, current.length));
const next = current.substring(0, start) + textToInsert + current.substring(end);
const nextCursor = start + textToInsert.length;
setPromptCursor(nextCursor);
return next;
});
};

const getSlashSuggestions = () => {
const cursor = Math.max(0, Math.min(inputSelection.start, inputText.length));
const textBeforeCursor = inputText.substring(0, cursor);
const lastWord = textBeforeCursor.split(/\s+/).pop() || "";
if (!lastWord.startsWith("/")) return [];
return slashCommands.filter((command) => command.name.startsWith(lastWord));
};

const slashSuggestions = getSlashSuggestions();

const selectPromptSuggestion = (item: PromptSuggestion) => {
const cursor = Math.max(0, Math.min(inputSelection.start, inputText.length));
const textBeforeCursor = inputText.substring(0, cursor);
const triggerIndex = textBeforeCursor.lastIndexOf("/");
if (triggerIndex === -1) return;

const nextText = textBeforeCursor.substring(0, triggerIndex) + item.name + " " + inputText.substring(cursor);
const nextCursor = triggerIndex + item.name.length + 1;
setInputText(nextText);
setPromptCursor(nextCursor);
};

  const handleCameraCapture = async () => {
    setIsPlusModalOpen(false);
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Camera Permission", "Please allow camera access to take photos/videos.");
        return;
      }

      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        quality: 0.9,
      });

      if (result.canceled || result.assets.length === 0) return;

      const asset = result.assets[0];
      const ext = asset.uri.split('.').pop() || 'jpg';
      const filename = `camera_${Date.now()}.${ext}`;

      addLocalAttachment(asset.uri, filename, 'image');
    } catch (err: any) {
      Alert.alert("Error", err?.message || "Could not capture media.");
    }
  };

  const handleGalleryPick = async () => {
    setIsPlusModalOpen(false);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Photos Permission", "Please allow photo access to attach media context.");
        return;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        quality: 0.9,
        allowsMultipleSelection: false,
      });

      if (result.canceled || result.assets.length === 0) return;

      const asset = result.assets[0];
      const ext = asset.uri.split('.').pop() || 'jpg';
      const filename = asset.fileName || `gallery_${Date.now()}.${ext}`;

      addLocalAttachment(asset.uri, filename, 'image');
    } catch (err: any) {
      Alert.alert("Error", err?.message || "Could not select media.");
    }
  };

  const handleDocumentPick = async () => {
    setIsPlusModalOpen(false);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        copyToCacheDirectory: true,
      });

      if (result.canceled || result.assets.length === 0) return;

      const asset = result.assets[0];
      const filename = asset.name || `doc_${Date.now()}`;

      addLocalAttachment(asset.uri, filename, 'document');
    } catch (err: any) {
      Alert.alert("Error", err?.message || "Could not select document.");
    }
  };

  const startAudioRecording = async () => {
    setIsPlusModalOpen(false);
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Permission Required", "Please allow microphone access to record audio.");
        return;
      }
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      setAudioRecording(recording);
      setIsRecordingAudio(true);
      showToast("Recording started...");
    } catch (err: any) {
      Alert.alert("Recording Error", err.message || "Failed to start recording.");
    }
  };

  const stopAudioRecording = async () => {
    if (!audioRecording) return;
    setIsRecordingAudio(false);
    try {
      await audioRecording.stopAndUnloadAsync();
      const uri = audioRecording.getURI();
      setAudioRecording(null);
      if (!uri) throw new Error("No recording URI found");

      const filename = `voice_${Date.now()}.m4a`;
      addLocalAttachment(uri, filename, 'audio');
    } catch (err: any) {
      Alert.alert("Recording Failed", err.message || "Failed to stop recording.");
    }
  };

const enqueuePrompt = (messageText: string) => {
const userMsg = messageText.trim();
if (!userMsg) return;

if (inputText === messageText) {
setInputText('');
}

const conversationId = activeConvoIdRef.current || ensureActiveConversationForContext();
const queuedProvider = getModelOption(selectedModel)?.provider || 'agy';
const nextQueue = [
...queuedPromptsRef.current,
{
id: `${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
content: userMsg,
model: selectedModel,
provider: queuedProvider,
effort: queuedProvider === 'claude' ? selectedClaudeEffort : selectedCodexEffort,
speed: selectedCodexSpeed,
thinking: selectedClaudeThinking,
target: selectedTarget,
project: selectedProjectRef.current,
conversationId,
},
];
setQueuedPromptList(nextQueue);
showToast("Prompt queued");
setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);
};

const cancelQueuedPrompt = (promptId: string) => {
const nextQueue = queuedPromptsRef.current.filter((item) => item.id !== promptId);
setQueuedPromptList(nextQueue);
showToast("Queued prompt cancelled");
};

const replaceQueuedConversationId = (oldConversationId: string, nextConversationId: string) => {
const nextQueue = queuedPromptsRef.current.map((item) =>
item.conversationId === oldConversationId ? { ...item, conversationId: nextConversationId } : item
);
setQueuedPromptList(nextQueue);
};

const processNextQueuedPrompt = () => {
if (loadingRef.current || queuedPromptsRef.current.length === 0) return;

const [nextPrompt, ...remainingQueue] = queuedPromptsRef.current;
setQueuedPromptList(remainingQueue);
sendChatMessage(nextPrompt.content, messagesRef.current, false, {
model: nextPrompt.model,
provider: nextPrompt.provider,
effort: nextPrompt.effort,
speed: nextPrompt.speed,
thinking: nextPrompt.thinking,
target: nextPrompt.target,
project: nextPrompt.project,
conversationId: nextPrompt.conversationId,
allowQueue: false,
});
};

  const sendChatMessage = async (
    messageText: string,
    baseMessages = messagesRef.current,
    clearPrompt = false,
    options?: Partial<QueuedPrompt> & { allowQueue?: boolean }
  ) => {
    const hasAttachments = localAttachments && localAttachments.length > 0;
    if (!messageText.trim() && !hasAttachments) return;

    const userMsg = messageText.trim();
    if (clearPrompt) {
      setInputText('');
    }

    if (loadingRef.current && options?.allowQueue !== false) {
      enqueuePrompt(userMsg);
      return;
    }

    const requestModel = options?.model || selectedModel;
    const requestProvider = options?.provider || getModelOption(requestModel)?.provider || 'agy';
    const requestEffort = options?.effort
      || (requestProvider === 'claude' ? selectedClaudeEffort : selectedCodexEffort);
    const requestSpeed = options?.speed || selectedCodexSpeed;
    const requestThinking = options?.thinking ?? selectedClaudeThinking;
    const requestTarget = options?.target || selectedTarget;
    const requestProject = options?.project || selectedProjectRef.current;

    // Add user message to display instantly (including local preview)
    const displayMsg = hasAttachments
      ? (localAttachments.map(a => `![Attached Image](${a.uri}?type=${a.type})`).join('\n') + '\n\n' + userMsg).trim()
      : userMsg;

    const updatedMessages = [...baseMessages, { role: 'user', content: displayMsg } as Message];
    updateMessages(updatedMessages);
    setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);

    setLoadingState(true);
    // Keep local copy of attachments to upload, then clear the state
    const attachmentsToUpload = [...localAttachments];
    setLocalAttachments([]); // Clear from input bar instantly so it looks sent

    try {
      const shouldReuseConversation = activeConvoIdRef.current
        && activeConvoProjectRef.current === requestProject
        && activeConvoProviderRef.current === requestProvider;
      const convoId = options?.conversationId || (shouldReuseConversation
      ? activeConvoIdRef.current
      : `temp_${requestProject}_${Math.random().toString(36).substring(2, 11)}`);
      if (!shouldReuseConversation || activeConvoIdRef.current !== convoId) {
        updateActiveConversation(convoId, requestProject, requestProvider);
      }

      // Upload local attachments if any right before posting task
      if (attachmentsToUpload.length > 0) {
        setUploadingMedia(true);
        try {
          for (const attachment of attachmentsToUpload) {
            await uploadMedia(attachment.uri, attachment.name, convoId);
          }
        } catch (uploadErr: any) {
          // Restore local attachments so they can try again on failure
          setLocalAttachments(attachmentsToUpload);
          throw uploadErr;
        } finally {
          setUploadingMedia(false);
        }
      }

      setTaskProgressEvents([{ seq: -1, type: 'progress', message: 'Preparing workspace...' }]);
      const startResponse = await callHostApi('/api/chat-tasks', {
        method: 'POST',
        body: JSON.stringify({
          message: userMsg,
          model: requestModel,
          provider: requestProvider,
          effort: requestEffort,
          speed: requestSpeed,
          thinking: requestThinking,
          workspace: requestProject,
          target: requestTarget,
          conversation_id: convoId
        })
      });

      if (!startResponse?.task_id) {
        throw new Error('Failed to start chat task');
      }

      const progressEvents: ChatTaskEvent[] = [];
      let lastSeq = -1;
      let response: any = null;

      while (true) {
        await wait(1500);
        const taskResponse = await callHostApi(`/api/chat-tasks/${startResponse.task_id}?after=${lastSeq}`);

        if (Array.isArray(taskResponse.events) && taskResponse.events.length > 0) {
          taskResponse.events.forEach((event: ChatTaskEvent) => {
            progressEvents.push(event);
            lastSeq = Math.max(lastSeq, event.seq);
          });
          setTaskProgressEvents([...progressEvents]);
          setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);
        }

        if (taskResponse.status === 'success' || taskResponse.status === 'error') {
          response = taskResponse.result;
          break;
        }
      }

      if (response && response.reply) {
        updateMessages([...updatedMessages, { role: 'assistant', content: response.reply }]);

        // Refresh conversation history list without changing current project.
        loadConversations(false);
        fetchUsageLimits();
        if (response.conversation_id && response.conversation_id !== convoId) {
          updateActiveConversation(response.conversation_id, requestProject, requestProvider);
          replaceQueuedConversationId(convoId, response.conversation_id);
        } else {
          updateActiveConversation(convoId, requestProject, requestProvider);
        }
      }
    } catch (err: any) {
      Alert.alert("Failed to send", err.message || "Failed to submit message to host.");
      if (clearPrompt) {
        setInputText(userMsg); // Restore prompt text on failure
      }
    } finally {
      setTaskProgressEvents([]);
      setLoadingState(false);
      setTimeout(() => scrollViewRef.current?.scrollToEnd({ animated: true }), 100);
      setTimeout(processNextQueuedPrompt, 0);
    }
  };

  const handleSend = async () => {
    sendChatMessage(inputText, messagesRef.current, true);
  };

  const handleQuestionResponse = (messageIndex: number, answer: string) => {
    const disabledMessages = messages.map((msg, index) =>
      index === messageIndex ? { ...msg, disabled: true } : msg
    );
    updateMessages(disabledMessages);
    sendChatMessage(answer, disabledMessages, false);
  };

  const handleDisconnect = () => {
    Alert.alert("Disconnect", "Are you sure you want to disconnect from this workspace?", [
      { text: "Cancel", style: "cancel" },
      { text: "Disconnect", style: "destructive", onPress: async () => {
        setIsConnected(false);
        await clearConnection();
        onDisconnect();
      }}
    ]);
  };

  const fetchUsageLimits = async () => {
    usageLimitControllerRef.current?.abort();
    const controller = new AbortController();
    usageLimitControllerRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), USAGE_LIMIT_TIMEOUT_MS);

    setLoadingUsage(true);
    setUsageLimitError('');
    try {
      const data = await callHostApi('/api/usage-limits', { signal: controller.signal });
      setUsageLimitData(data);
    } catch (err: any) {
      console.error("Error loading usage limits:", err);
      if (usageLimitControllerRef.current !== controller) {
        return;
      }
      if (controller.signal.aborted) {
        setUsageLimitError("Showing cached usage data. Refresh is taking longer than usual while the current task is running.");
      } else {
        setUsageLimitError(err?.message || "Showing cached usage data. Refresh failed.");
      }
    } finally {
      clearTimeout(timeoutId);
      if (usageLimitControllerRef.current === controller) {
        usageLimitControllerRef.current = null;
        setLoadingUsage(false);
      }
    }
  };

  const getActiveUsagePercentage = () => {
    if (!usageLimitData) return 0;
    if (isCodexModel(selectedModel)) {
      const primary = usageLimitData.codexRateLimits?.primary;
      if (primary) {
        return usageMode === 'usage'
          ? Number(primary.usedPercent ?? 0)
          : Number(primary.remainingPercent ?? Math.max(0, 100 - (primary.usedPercent ?? 0)));
      }
    }
    const bucket = getUsageBucketForModel(selectedModel);
    const activeHourlyPercent = Number(usageLimitData[`${bucket.key}HourlyPercent`] ?? 0);
    return usageMode === 'usage' ? activeHourlyPercent : Math.max(0, 100 - activeHourlyPercent);
  };

  const getUsageMetric = (bucket: UsageBucketKey, period: UsagePeriodKey, metric: 'Used' | 'Limit' | 'Percent') => {
    const value = usageLimitData?.[`${bucket}${period}${metric}`];
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
  };

  const renderCircularChart = (percent: number, color: string) => {
    const size = 28;
    const strokeWidth = 3;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const strokeDashoffset = circumference - (Math.min(100, Math.max(0, percent)) / 100) * circumference;

    return (
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Text style={[styles.usageRowPercent, { color: theme.textPrimary }]}>{percent.toFixed(1)}%</Text>
        <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)'}
            strokeWidth={strokeWidth}
            fill="none"
          />
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={color}
            strokeWidth={strokeWidth}
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        </Svg>
      </View>
    );
  };

  const renderUsageLimitRow = (
    bucket: UsageBucketKey,
    period: UsagePeriodKey,
    label: string,
  ) => {
    const used = getUsageMetric(bucket, period, 'Used');
    const limit = getUsageMetric(bucket, period, 'Limit');
    const usedPercent = getUsageMetric(bucket, period, 'Percent');
    const displayPercent = usageMode === 'usage' ? usedPercent : Math.max(0, 100 - usedPercent);
    const remainingTokens = Math.max(0, limit - used);

    return (
      <View style={styles.usageRow}>
        <View style={styles.usageRowLabel}>
          <Text style={[styles.usageRowName, { color: theme.textPrimary }]}>{label}</Text>
          <Text style={[styles.usageRowDesc, { color: theme.textSecondary }]}>
            {usageMode === 'usage'
              ? `Used ${used.toLocaleString()} tokens (${usedPercent.toFixed(1)}%)`
              : `${remainingTokens.toLocaleString()} tokens (${Math.max(0, 100 - usedPercent).toFixed(1)}%) remaining`
            }
          </Text>
        </View>
        {renderCircularChart(displayPercent, theme.statusGreen)}
      </View>
    );
  };

  const formatCodexResetDate = (timestampSeconds?: number | null) => {
    if (!timestampSeconds) return '';
    try {
      return new Date(timestampSeconds * 1000).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return '';
    }
  };

  const formatCodexWindowLabel = (windowDurationMins?: number | null) => {
    if (windowDurationMins === 10080) return 'Weekly Limit';
    if (windowDurationMins === 300) return 'Five Hour Limit';
    if (windowDurationMins && windowDurationMins >= 60) {
      const hours = windowDurationMins / 60;
      return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} Hour Limit`;
    }
    return 'Usage Limit';
  };

  const renderCodexRateLimitRow = (windowData: any, fallbackLabel: string) => {
    if (!windowData) return null;
    const usedPercent = Number(windowData.usedPercent ?? 0);
    const remainingPercent = Number(windowData.remainingPercent ?? Math.max(0, 100 - usedPercent));
    const displayPercent = usageMode === 'usage' ? usedPercent : remainingPercent;
    const resetDate = formatCodexResetDate(windowData.resetsAt);

    return (
      <View style={styles.usageRow}>
        <View style={styles.usageRowLabel}>
          <Text style={[styles.usageRowName, { color: theme.textPrimary }]}>
            {formatCodexWindowLabel(windowData.windowDurationMins) || fallbackLabel}
          </Text>
          <Text style={[styles.usageRowDesc, { color: theme.textSecondary }]}>
            {usageMode === 'usage'
              ? `Used ${usedPercent.toFixed(0)}% of your Codex account limit${resetDate ? `; resets ${resetDate}` : ''}`
              : `${remainingPercent.toFixed(0)}% remaining${resetDate ? `; resets ${resetDate}` : ''}`
            }
          </Text>
        </View>
        {renderCircularChart(displayPercent, theme.statusGreen)}
      </View>
    );
  };

  const openUsageModal = () => {
    setIsUsageModalOpen(true);
    fetchUsageLimits();
  };

  const closeUsageModal = () => {
    usageLimitControllerRef.current?.abort();
    usageLimitControllerRef.current = null;
    setLoadingUsage(false);
    setIsUsageModalOpen(false);
  };

  // Group conversations by project, mirroring desktop sidebar grouping
  const groupedConversations = conversations.reduce((acc, convo) => {
    const proj = convo.project || 'Other';
    if (!acc[proj]) acc[proj] = [];
    acc[proj].push(convo);
    return acc;
  }, {} as { [key: string]: Conversation[] });
  const activeConversation = conversations.find((convo) => convo.id === activeConvoId);
  const headerConversationTitle = activeConversation?.title || "Untitled Conversation";
  const isPromptDisabled = isInitializingChat;

  const renderMessageContent = (content: string, role: 'user' | 'assistant') => {
    const imageRegex = /!\[.*?\]\((.*?)\)/g;
    const matches = [...content.matchAll(imageRegex)];
    const cleanText = content.replace(imageRegex, '').trim();

    const renderTextContent = (text: string) => {
      const segments = parseMessageSegments(text);
      return segments.map((segment, idx) => {
        if (segment.type === 'details') {
          return (
            <CollapsibleDetailsCard
              key={idx}
              summary={segment.summary || 'Details'}
              body={segment.body || ''}
              theme={theme}
              fontSize={selectedFontSize}
            />
          );
        } else {
          return segment.text?.trim() ? (
            <Text
              key={idx}
              style={
                role === 'user'
                  ? [styles.userText, { fontSize: selectedFontSize, lineHeight: selectedFontSize * 1.4 }]
                  : [styles.assistantText, { color: theme.textPrimary, fontSize: selectedFontSize, lineHeight: selectedFontSize * 1.4 }]
              }
            >
              {segment.text}
            </Text>
          ) : null;
        }
      });
    };

    if (matches.length === 0) {
      return (
        <View style={{ gap: 8 }}>
          {renderTextContent(content)}
        </View>
      );
    }

    return (
      <View style={{ gap: 8 }}>
        {matches.map((match, idx) => {
          const relativeUrl = match[1];
          const isLocal = relativeUrl.startsWith('file://') || relativeUrl.startsWith('content://') || relativeUrl.startsWith('ph://');
          let absoluteUrl = (relativeUrl.startsWith('http') || isLocal) ? relativeUrl : `${hostBaseUrl}${relativeUrl}`;

          if (absoluteUrl.includes('/api/media') && authToken && !absoluteUrl.includes('token=')) {
            const separator = absoluteUrl.includes('?') ? '&' : '?';
            absoluteUrl = `${absoluteUrl}${separator}token=${encodeURIComponent(authToken)}`;
          }

          const mediaType = getMediaType(absoluteUrl);

          if (mediaType === 'image') {
            return (
              <Image
                key={idx}
                source={{
                  uri: absoluteUrl,
                  headers: (absoluteUrl.startsWith('http') && authToken) ? {
                    Authorization: `Bearer ${authToken}`
                  } : undefined
                }}
                style={styles.chatImage}
                resizeMode="cover"
              />
            );
          } else if (mediaType === 'video') {
            return (
              <VideoPlayerView key={idx} url={absoluteUrl} />
            );
          } else if (mediaType === 'audio') {
            return (
              <AudioPlayerView key={idx} url={absoluteUrl} theme={theme} />
            );
          } else {
            const filename = absoluteUrl.split('/').pop()?.split('?')[0] || 'attachment';
            const cleanName = filename.replace('media__', '');
            return (
              <DocumentAttachmentView key={idx} url={absoluteUrl} filename={cleanName} theme={theme} />
            );
          }
        })}
        {cleanText ? renderTextContent(cleanText) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.bgSecondary }]} edges={['top', 'left', 'right']}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} backgroundColor={theme.bgPrimary} />

      {/* Sidebar Backdrop Overlay */}
      {isSidebarOpen && (
        <Animated.View style={[styles.sidebarBackdrop, { opacity: backdropOpacity }]}>
          <TouchableOpacity
            style={styles.sidebarBackdropTouchable}
            activeOpacity={1}
            onPress={toggleSidebar}
          />
        </Animated.View>
      )}

      {/* Slide-in Left Sidebar */}
      <Animated.View style={[styles.sidebar, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor, opacity: sidebarOpacity, transform: [{ translateX: sidebarAnim }] }]}>
        <View style={[styles.sidebarHeader, { borderBottomColor: theme.borderColor }]}>
<Text style={[styles.sidebarLogo, { color: theme.accent }]}>{'\u25B2'} KookAI</Text>
          <TouchableOpacity style={styles.closeSidebarBtn} onPress={toggleSidebar}>
            <Text style={{ color: theme.textSecondary, fontSize: 20 }}>✕</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={[styles.newChatBtn, { backgroundColor: theme.accent }]} onPress={() => { startNewChat(); toggleSidebar(); }}>
          <Text style={styles.newChatBtnText}>+ New Conversation</Text>
        </TouchableOpacity>

        <ScrollView style={styles.sidebarScroll} contentContainerStyle={styles.sidebarContent}>
          {loadingConvList ? (
            <ActivityIndicator size="small" color={theme.accent} style={{ marginTop: 20 }} />
          ) : Object.keys(groupedConversations).length === 0 ? (
            <Text style={[styles.emptyConvoText, { color: theme.textMuted }]}>No conversations found</Text>
          ) : (
            Object.keys(groupedConversations).map((projName) => (
              <View key={projName} style={styles.projectGroup}>
                <Text style={[styles.projectHeader, { color: theme.textSecondary }]}>{projName.toUpperCase()}</Text>
                <View style={styles.projectItems}>
                  {(() => {
                    const allItems = groupedConversations[projName];
                    const displayedItems = expandedProjects[projName] ? allItems : allItems.slice(0, 5);
                    const hasMore = allItems.length > 5;
                    return (
                      <>
                        {displayedItems.map((convo) => (
                          <TouchableOpacity
                            key={convo.id}
                            style={[
                              styles.sidebarConvoItem,
                              activeConvoId === convo.id && { backgroundColor: theme.bgActive }
                            ]}
                            onPress={() => {
                              selectConversation(convo.id, convo.project);
                              toggleSidebar();
                            }}
                          >
                            <Text
                              style={[
                                styles.sidebarConvoText,
                                { color: activeConvoId === convo.id ? theme.textPrimary : theme.textSecondary },
                                activeConvoId === convo.id && { fontWeight: '700' }
                              ]}
                              numberOfLines={1}
                            >
                              💬 {convo.title || "Untitled Conversation"}
                            </Text>
                          </TouchableOpacity>
                        ))}
                        {hasMore && !expandedProjects[projName] && (
                          <TouchableOpacity
                            style={styles.seeAllBtn}
                            onPress={() => setExpandedProjects(prev => ({ ...prev, [projName]: true }))}
                          >
                            <Text style={[styles.seeAllText, { color: theme.accent }]}>See all ({allItems.length - 5} more)</Text>
                          </TouchableOpacity>
                        )}
                        {hasMore && expandedProjects[projName] && (
                          <TouchableOpacity
                            style={styles.seeAllBtn}
                            onPress={() => setExpandedProjects(prev => ({ ...prev, [projName]: false }))}
                          >
                            <Text style={[styles.seeAllText, { color: theme.accent }]}>Show less</Text>
                          </TouchableOpacity>
                        )}
                      </>
                    );
                  })()}
                </View>
              </View>
            ))
          )}
        </ScrollView>

        {/* Bottom actions inside sidebar */}
        <View style={[styles.sidebarFooter, { borderTopColor: theme.borderColor }]}>
          <TouchableOpacity style={[styles.sidebarSettingsBtn, { borderColor: theme.borderColor }]} onPress={openSettingsModal}>
            <Text style={[styles.sidebarSettingsIcon, { color: theme.textSecondary }]}>⚙</Text>
            <Text style={[styles.sidebarSettingsText, { color: theme.textPrimary }]}>Settings</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.sidebarDisconnectBtn} onPress={handleDisconnect}>
            <Text style={styles.sidebarDisconnectText}>Disconnect</Text>
          </TouchableOpacity>
        </View>
      </Animated.View>

      {/* Main Chat Area */}
      <View style={[styles.header, { backgroundColor: theme.bgPrimary, borderBottomWidth: 1, borderBottomColor: theme.borderColor }]}>
        <View style={styles.headerLeft}>
          <TouchableOpacity style={styles.menuBtn} onPress={toggleSidebar}>
            <Text style={{ color: theme.textPrimary, fontSize: 24 }}>☰</Text>
          </TouchableOpacity>
          <View style={styles.headerTitleContainer}>
            <Text style={[styles.headerTitle, { color: theme.textPrimary }]} numberOfLines={1}>
              {headerConversationTitle}
            </Text>
          </View>
        </View>
        <TouchableOpacity style={styles.themeToggleBtn} onPress={toggleThemeMode}>
          <Text style={{ fontSize: 20 }}>{selectedThemeMode === 'light' ? '🌙' : '☀️'}</Text>
        </TouchableOpacity>
      </View>

      <KeyboardAvoidingView
        style={styles.chatArea}
        enabled={Platform.OS === 'ios'}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        <Animated.View style={{ opacity: chatFadeAnim, transform: [{ translateY: chatTranslateY }], flex: 1 }}>
          <ScrollView
            ref={scrollViewRef}
            style={styles.messageScroll}
            contentContainerStyle={styles.messageContent}
            onContentSizeChange={() => {
              if (pendingConversationScrollRef.current) {
                pendingConversationScrollRef.current = false;
                scrollMessagesToBottom(false);
              }
            }}
          >
          {isInitializingChat ? (
            <View style={styles.initializingView}>
              <ActivityIndicator size="small" color={theme.accent} />
              <Text style={[styles.initializingTitle, { color: theme.textPrimary }]}>Preparing workspace</Text>
              <Text style={[styles.initializingSubtitle, { color: theme.textSecondary }]}>Loading your latest conversation...</Text>
            </View>
          ) : messages.length === 0 && queuedPrompts.length === 0 ? (
            <View style={styles.emptyView}>
              <Text style={[styles.emptyTitle, { color: theme.textPrimary }]}>What should we build today?</Text>
              <Text style={[styles.emptySubtitle, { color: theme.textSecondary }]}>Interact with your desktop files, run workspace tasks, or audit goals directly from your mobile device.</Text>
            </View>
          ) : (
            messages.map((msg, index) => {
              const question = msg.role === 'assistant' ? parseQuestionPayload(msg.content) : null;

              if (question) {
                return (
                  <QuestionCard
                    key={index}
                    question={question}
                    disabled={loading || Boolean(msg.disabled) || index !== messages.length - 1}
                    theme={theme}
                    isDark={isDark}
                    onSubmit={(answer) => handleQuestionResponse(index, answer)}
                  />
                );
              }

              return (
                <TouchableOpacity
                  key={index}
                  activeOpacity={0.9}
                  onLongPress={() => handleCopyMessage(msg.content)}
                  delayLongPress={400}
                  style={[
                    styles.messageBubble,
                    msg.role === 'user'
                      ? [styles.userBubble, { backgroundColor: theme.accent }]
                      : [styles.assistantBubble, { backgroundColor: theme.bgActive, borderColor: theme.borderColor }]
                  ]}
                >
                  {renderMessageContent(msg.content, msg.role)}
                </TouchableOpacity>
              );
            })
          )}
          {loading && !isInitializingChat && (
            taskProgressEvents.length === 0 ? (
              <View 
                style={[
                  styles.messageBubble, 
                  styles.assistantBubble, 
                  { 
                    backgroundColor: theme.bgActive, 
                    borderColor: theme.borderColor,
                    flexDirection: 'row',
                    alignItems: 'center',
                    gap: 8,
                    alignSelf: 'flex-start',
                    marginVertical: 4
                  }
                ]}
              >
                <ActivityIndicator size="small" color={theme.accent} />
                <Text style={[styles.assistantText, { color: theme.textSecondary, fontSize: selectedFontSize }]}>
                  Thinking...
                </Text>
              </View>
            ) : (
              <View 
                style={[
                  styles.messageBubble, 
                  styles.assistantBubble, 
                  { 
                    backgroundColor: theme.bgActive, 
                    borderColor: theme.borderColor,
                    alignSelf: 'flex-start',
                    marginVertical: 4,
                    width: '85%'
                  }
                ]}
              >
                <View style={{ gap: 8 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <ActivityIndicator size="small" color={theme.accent} />
                    <Text style={[styles.runningTaskTitle, { color: theme.textPrimary, fontSize: selectedFontSize, fontWeight: '700' }]}>
                      Running task...
                    </Text>
                  </View>
                  <View style={{ gap: 6, marginTop: 4 }}>
                    {taskProgressEvents.slice(-8).map((event, idx) => {
                      const { icon, cleanMessage } = getEventIconAndCleanMessage(event.message);
                      return (
                        <Text 
                          key={event.seq !== undefined && event.seq !== null ? event.seq : idx}
                          style={[
                            styles.progressLogLine, 
                            { 
                              color: event.type === 'error' ? theme.statusRed : theme.textSecondary, 
                              fontSize: Math.max(11, selectedFontSize - 1),
                              lineHeight: Math.max(11, selectedFontSize - 1) * 1.4
                            }
                          ]}
                          numberOfLines={2}
                        >
                          • {icon} {cleanMessage}
                        </Text>
                      );
                    })}
                  </View>
                </View>
              </View>
            )
          )}
          {queuedPrompts.map((item, index) => (
            <View
              key={item.id}
              style={[
                styles.queuedPromptBubble,
                {
                  backgroundColor: isDark ? 'rgba(59, 130, 246, 0.1)' : 'rgba(37, 99, 235, 0.06)',
                  borderColor: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(37, 99, 235, 0.22)',
                },
              ]}
            >
              <View style={styles.queuedPromptHeader}>
                <Text style={[styles.queuedPromptStatus, { color: theme.accent }]}>
                  Queued #{index + 1}
                </Text>
                <TouchableOpacity
                  style={styles.queuedPromptCancelBtn}
                  onPress={() => cancelQueuedPrompt(item.id)}
                >
                  <Text style={[styles.queuedPromptCancelText, { color: theme.statusRed }]}>Cancel</Text>
                </TouchableOpacity>
              </View>
              <Text style={[styles.queuedPromptText, { color: theme.textPrimary }]}>{item.content}</Text>
              <Text style={[styles.queuedPromptMeta, { color: theme.textMuted }]} numberOfLines={1}>
                {item.model}
                {item.provider === 'codex' ? ` · ${item.effort} · ${item.speed}` : ''}
                {item.provider === 'claude' ? ` · ${item.effort} · Thinking ${item.thinking ? 'On' : 'Off'}` : ''}
                {item.provider === 'kimi' ? ' · Thinking On' : ''}
                {` · ${item.target}`}
              </Text>
            </View>
          ))}
          </ScrollView>
        </Animated.View>

        {/* Web-matching Input Bar Area */}
        <View style={[styles.promptSection, { backgroundColor: theme.bgSecondary, paddingBottom: promptBottomPadding, marginBottom: promptKeyboardOffset }]}>
          {slashSuggestions.length > 0 && (
            <View style={[styles.autocompletePopup, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
              {slashSuggestions.map((item, index) => (
                <TouchableOpacity
                  key={item.name}
                  activeOpacity={0.85}
                  style={[
                    styles.autocompleteItem,
                    index === 0 && { backgroundColor: isDark ? 'rgba(255, 255, 255, 0.07)' : 'rgba(0, 0, 0, 0.04)' },
                  ]}
                  onPress={() => selectPromptSuggestion(item)}
                >
                  <View style={styles.autocompleteItemLeft}>
                    <Text style={[styles.autocompleteSymbol, { color: theme.accent }]}>{item.name.charAt(0)}</Text>
                    <Text style={[styles.autocompleteText, { color: theme.textPrimary }]}>{item.name.slice(1)}</Text>
                    <Text style={[styles.autocompleteDesc, { color: theme.textMuted }]} numberOfLines={1}>— {item.desc}</Text>
                  </View>
                  <Text style={[styles.autocompleteItemRight, { color: theme.textMuted }]}>{item.type}</Text>
                </TouchableOpacity>
              ))}
            </View>
          )}
          <View style={[styles.promptInputCard, isPromptDisabled && styles.promptInputCardDisabled, { backgroundColor: theme.bgInput, borderColor: theme.borderColor }]}>
            {isRecordingAudio ? (
              <View style={styles.recordingPanel}>
                <View style={styles.recordingIndicatorContainer}>
                  <View style={styles.recordingDot} />
                  <Text style={[styles.recordingText, { color: theme.textPrimary }]}>Recording Voice Note...</Text>
                </View>
                <TouchableOpacity style={[styles.stopRecordBtn, { backgroundColor: '#ef4444' }]} onPress={stopAudioRecording}>
                  <Text style={styles.stopRecordBtnText}>Stop & Attach</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <>
                {localAttachments.length > 0 && (
                  <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    contentContainerStyle={styles.attachmentPreviewContainer}
                  >
                    {localAttachments.map((item) => (
                      <View key={item.id} style={styles.attachmentThumbnailWrapper}>
                        {item.type === 'image' || item.type === 'video' ? (
                          <Image source={{ uri: item.uri }} style={styles.attachmentThumbnail} />
                        ) : (
                          <View style={[styles.attachmentDocumentIcon, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
                            <Text style={{ fontSize: 24 }}>{item.type === 'audio' ? '🎤' : '📄'}</Text>
                            <Text style={[styles.attachmentDocumentText, { color: theme.textSecondary }]} numberOfLines={1}>
                              {item.name}
                            </Text>
                          </View>
                        )}
                        <TouchableOpacity
                          style={styles.attachmentDeleteBtn}
                          activeOpacity={0.7}
                          onPress={() => removeLocalAttachment(item.id)}
                        >
                          <Text style={styles.attachmentDeleteText}>×</Text>
                        </TouchableOpacity>
                      </View>
                    ))}
                  </ScrollView>
                )}
                <TextInput
                  ref={promptInputRef}
                  style={[styles.promptInputText, { color: theme.textPrimary, fontSize: selectedFontSize, lineHeight: selectedFontSize * 1.4 }]}
                  editable={!isPromptDisabled}
                  placeholder={isPromptDisabled ? "Preparing workspace..." : "Ask anything, @ to mention, / for actions"}
                  placeholderTextColor={theme.textMuted}
                  value={inputText}
                  selection={inputSelection}
                  onChangeText={setInputText}
                  onSelectionChange={(event) => {
                    inputSelectionRef.current = event.nativeEvent.selection;
                    setInputSelection(event.nativeEvent.selection);
                  }}
                  multiline
                />

                {/* Tools Row inside prompt card */}
                <View style={styles.promptToolRow}>
                  <View style={styles.toolRowLeft}>
                    <TouchableOpacity
                      style={[styles.toolBtn, { backgroundColor: isPlusModalOpen ? theme.accent : theme.bgSecondary }]}
                      onPress={() => setIsPlusModalOpen(true)}
                      disabled={uploadingMedia || isPromptDisabled}
                    >
                      {uploadingMedia ? (
                        <ActivityIndicator size="small" color={theme.textSecondary} />
                      ) : (
                        <Text style={{ color: isPlusModalOpen ? '#ffffff' : theme.textSecondary, fontSize: 16 }}>＋</Text>
                      )}
                    </TouchableOpacity>

                    {/* Model Selector Dropdown */}
                    <TouchableOpacity
                      style={[styles.modelPickerBtn, { backgroundColor: theme.bgSecondary }]}
                      onPress={() => setIsModelModalOpen(true)}
                      disabled={isPromptDisabled}
                    >
                      <Text style={[styles.modelPickerText, { color: theme.textPrimary }]}>
                        {isCodexModel(selectedModel)
                          ? `${getModelLabel(selectedModel)} ${selectedCodexEffort}`
                          : getModelLabel(selectedModel)}
                      </Text>
                      <Text style={{ color: theme.textSecondary, fontSize: 10, marginLeft: 4 }}>▼</Text>
                    </TouchableOpacity>
                  </View>

                  <View style={styles.toolRowRight}>
                    <TouchableOpacity
                      style={[
                        styles.toolBtn,
                        styles.voiceToolBtn,
                        { backgroundColor: isVoiceRecording ? theme.accent : theme.bgSecondary },
                      ]}
                      onPress={handleToggleVoiceInput}
                      disabled={isPromptDisabled}
                    >
                      {isVoiceRecording ? (
                        renderVoiceListeningIndicator()
                      ) : (
                        <Text style={{ color: theme.textSecondary, fontSize: 14 }}>🎤</Text>
                      )}
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.sendBtnRound, isPromptDisabled && styles.sendBtnDisabled, { backgroundColor: theme.accent }]}
                      onPress={handleSend}
                      disabled={isPromptDisabled}
                    >
                      <Text style={styles.sendIcon}>➤</Text>
                    </TouchableOpacity>
                  </View>
                </View>
                {(isCodexModel(selectedModel) || isClaudeModel(selectedModel)) && (
                  <View style={styles.codexOptionsRow}>
                    {(isCodexModel(selectedModel) || getModelOption(selectedModel)?.supportsClaudeEffort) && (
                      <TouchableOpacity
                        style={[styles.codexOptionBtn, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}
                        onPress={() => setIsEffortModalOpen(true)}
                        disabled={isPromptDisabled}
                      >
                        <Text style={[styles.codexOptionLabel, { color: theme.textMuted }]}>Effort</Text>
                        <Text style={[styles.codexOptionValue, { color: theme.textPrimary }]}>
                          {isClaudeModel(selectedModel) ? selectedClaudeEffort : selectedCodexEffort}
                        </Text>
                      </TouchableOpacity>
                    )}
                    {isCodexModel(selectedModel) ? (
                      <TouchableOpacity
                        style={[styles.codexOptionBtn, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}
                        onPress={() => setIsSpeedModalOpen(true)}
                        disabled={isPromptDisabled}
                      >
                        <Text style={[styles.codexOptionLabel, { color: theme.textMuted }]}>Speed</Text>
                        <Text style={[styles.codexOptionValue, { color: theme.textPrimary }]}>{selectedCodexSpeed}</Text>
                      </TouchableOpacity>
                    ) : (
                      <View
                        style={[
                          styles.codexOptionBtn,
                          styles.claudeThinkingOption,
                          { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor },
                        ]}
                      >
                        <View>
                          <Text style={[styles.codexOptionLabel, { color: theme.textMuted }]}>Thinking</Text>
                          <Text style={[styles.codexOptionValue, { color: theme.textPrimary }]}>
                            {selectedClaudeThinking ? 'On' : 'Off'}
                          </Text>
                        </View>
                        <Switch
                          value={selectedClaudeThinking}
                          onValueChange={setSelectedClaudeThinking}
                          disabled={isPromptDisabled || Boolean(getModelOption(selectedModel)?.thinkingRequired)}
                          trackColor={{ false: theme.borderColor, true: theme.accent }}
                          thumbColor="#ffffff"
                        />
                      </View>
                    )}
                  </View>
                )}
              </>
            )}
          </View>

          {/* Bottom Row under Prompt Card */}
          <View style={styles.promptBottomBar}>
            <View style={styles.bottomBarLeft}>
              {/* Target Selector Dropdown */}
              <TouchableOpacity
                style={styles.targetPickerBtn}
                onPress={() => setIsTargetModalOpen(true)}
                disabled={isPromptDisabled}
              >
                <Text style={{ marginRight: 4 }}>🖥</Text>
                <Text style={[styles.targetPickerText, { color: theme.textSecondary }]}>{selectedTarget}</Text>
                <Text style={{ color: theme.textSecondary, fontSize: 8, marginLeft: 4 }}>▼</Text>
              </TouchableOpacity>

              {/* Project Selector Dropdown */}
              <TouchableOpacity
                style={styles.projectPickerBtn}
                onPress={() => setIsProjectModalOpen(true)}
                disabled={isPromptDisabled}
              >
                <Text style={{ marginRight: 4 }}>▣</Text>
                <Text style={[styles.projectPickerText, { color: theme.textSecondary }]} numberOfLines={1}>{selectedProject}</Text>
                <Text style={{ color: theme.textSecondary, fontSize: 8, marginLeft: 4 }}>▼</Text>
              </TouchableOpacity>
            </View>

            <View style={styles.bottomBarRight}>
              {/* Circular Usage Chart Button */}
              <TouchableOpacity style={styles.usageBtnCircleContainer} onPress={openUsageModal}>
                <Svg width={18} height={18} viewBox="0 0 18 18">
                  {/* Background Circle */}
                  <Circle
                    cx={9}
                    cy={9}
                    r={6.5}
                    stroke={isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.15)'}
                    strokeWidth={2}
                    fill="none"
                  />
                  {/* Progress Circle */}
                  <Circle
                    cx={9}
                    cy={9}
                    r={6.5}
                    stroke={connectionStatusColor}
                    strokeWidth={2}
                    fill="none"
                    strokeDasharray={2 * Math.PI * 6.5}
                    strokeDashoffset={2 * Math.PI * 6.5 - (getActiveUsagePercentage() / 100) * (2 * Math.PI * 6.5)}
                    strokeLinecap="round"
                    transform="rotate(-90 9 9)"
                  />
                </Svg>
              </TouchableOpacity>

              {/* Connection Status Dot */}
              <View style={[styles.statusDot, { backgroundColor: connectionStatusColor }]} />
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>

      {/* -------------------- MODAL DIALOGS -------------------- */}

      {/* Add Context bottom-sheet overlay */}
      <Modal visible={isPlusModalOpen} transparent animationType="slide" onRequestClose={() => setIsPlusModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsPlusModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Add Context</Text>
              <TouchableOpacity onPress={() => setIsPlusModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.bottomSheetContent}>
              <TouchableOpacity style={styles.contextMenuItem} onPress={handleCameraCapture} disabled={uploadingMedia}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>📷</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Camera</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Take a photo or capture a video</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={handleGalleryPick} disabled={uploadingMedia}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>🖼</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Gallery</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Choose images or videos from library</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={handleDocumentPick} disabled={uploadingMedia}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>📄</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Document</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Attach a PDF, code, or other text file</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={startAudioRecording} disabled={uploadingMedia}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>🎤</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Voice Note</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Record and attach audio message</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={() => insertPromptText("@")}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>@</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Mentions</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Reference files from the workspace</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={() => insertPromptText("/")}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>/</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Actions</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Insert a slash command</Text>
                </View>
              </TouchableOpacity>

              <TouchableOpacity style={styles.contextMenuItem} onPress={() => insertPromptText("/browser ")}>
                <Text style={[styles.contextMenuIcon, { color: theme.textSecondary }]}>◉</Text>
                <View style={styles.contextMenuTextBlock}>
                  <Text style={[styles.contextMenuTitle, { color: theme.textPrimary }]}>Browser context</Text>
                  <Text style={[styles.contextMenuDesc, { color: theme.textSecondary }]}>Start a browser command</Text>
                </View>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Model Picker bottom-sheet overlay */}
      <Modal visible={isModelModalOpen} transparent animationType="slide" onRequestClose={() => setIsModelModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsModelModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Select AI Model</Text>
              <TouchableOpacity onPress={() => setIsModelModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.bottomSheetList}>
              {modelsList.map((model) => {
                const badge = getBadgeStyles(model.value, isDark);
                const isActive = selectedModel === model.value;
                return (
                  <TouchableOpacity
                    key={model.value}
                    style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                    onPress={() => {
                      applySelectedModel(model.value);
                      setIsModelModalOpen(false);
                    }}
                  >
                    <View style={styles.modalItemLeft}>
                      <View style={[styles.badge, { backgroundColor: badge.bg }]}>
                        <Text style={[styles.badgeText, { color: badge.color }]}>{badge.text}</Text>
                      </View>
                      <View style={styles.modelInfo}>
                        <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{model.label || model.value}</Text>
                        <Text style={[styles.modelDesc, { color: theme.textSecondary }]} numberOfLines={1}>{model.desc}</Text>
                      </View>
                    </View>
                    {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Codex / Claude effort picker */}
      <Modal visible={isEffortModalOpen} transparent animationType="slide" onRequestClose={() => setIsEffortModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsEffortModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>
                {isClaudeModel(selectedModel) ? 'Claude Effort' : 'Codex Effort'}
              </Text>
              <TouchableOpacity onPress={() => setIsEffortModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.bottomSheetContent}>
              {(isClaudeModel(selectedModel) ? getClaudeEfforts(selectedModel) : getCodexEfforts(selectedModel)).map((item) => {
                const isClaudeEffort = isClaudeModel(selectedModel);
                const isActive = isClaudeEffort
                  ? selectedClaudeEffort === item.value
                  : selectedCodexEffort === item.value;
                return (
                  <TouchableOpacity
                    key={item.value}
                    style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                    onPress={() => {
                      if (isClaudeEffort) {
                        setSelectedClaudeEffort(item.value as ClaudeEffort);
                      } else {
                        setSelectedCodexEffort(item.value as CodexEffort);
                      }
                      setIsEffortModalOpen(false);
                    }}
                  >
                    <View style={styles.modelInfo}>
                      <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{item.value}</Text>
                      <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{item.desc}</Text>
                    </View>
                    {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        </View>
      </Modal>

      {/* Codex speed picker */}
      <Modal visible={isSpeedModalOpen} transparent animationType="slide" onRequestClose={() => setIsSpeedModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsSpeedModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Codex Speed</Text>
              <TouchableOpacity onPress={() => setIsSpeedModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.bottomSheetContent}>
              {getCodexSpeeds(selectedModel).map((item) => {
                const isActive = selectedCodexSpeed === item.value;
                return (
                  <TouchableOpacity
                    key={item.value}
                    style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                    onPress={() => {
                      setSelectedCodexSpeed(item.value);
                      setIsSpeedModalOpen(false);
                    }}
                  >
                    <View style={styles.modelInfo}>
                      <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{item.value}</Text>
                      <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{item.desc}</Text>
                    </View>
                    {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        </View>
      </Modal>

      {/* Target Picker Modal overlay */}
      <Modal visible={isTargetModalOpen} transparent animationType="slide" onRequestClose={() => setIsTargetModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsTargetModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Select Execution Target</Text>
              <TouchableOpacity onPress={() => setIsTargetModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.bottomSheetContent}>
              {targetsList.map((target) => {
                const isActive = selectedTarget === target.value;
                return (
                  <TouchableOpacity
                    key={target.value}
                    style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                    onPress={() => {
                      setSelectedTarget(target.value);
                      setIsTargetModalOpen(false);
                    }}
                  >
                    <View style={styles.modelInfo}>
                      <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{target.value}</Text>
                      <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{target.desc}</Text>
                    </View>
                    {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        </View>
      </Modal>

 {/* Project Picker Modal overlay */}
 <Modal visible={isProjectModalOpen} transparent animationType="slide" onRequestClose={() => setIsProjectModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsProjectModalOpen(false)} />
          <View style={[styles.bottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Select Project</Text>
              <TouchableOpacity onPress={() => setIsProjectModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.bottomSheetList}>
              {loadingProjects ? (
                <ActivityIndicator size="small" color={theme.accent} style={{ marginVertical: 18 }} />
              ) : (
                projects.map((project) => {
                  const isActive = selectedProject === project;
                  return (
                    <TouchableOpacity
                      key={project}
                      style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                      onPress={() => handleSelectProject(project)}
                    >
                      <View style={styles.modelInfo}>
                        <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{project}</Text>
                        <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>Run new messages in this workspace</Text>
                      </View>
                      {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                    </TouchableOpacity>
                  );
                })
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Settings Modal overlay */}
      <Modal visible={isSettingsModalOpen} transparent animationType="slide" onRequestClose={() => setIsSettingsModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setIsSettingsModalOpen(false)} />
          <View style={[styles.bottomSheet, styles.settingsBottomSheet, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.bottomSheetHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.bottomSheetTitle, { color: theme.textPrimary }]}>Settings</Text>
              <TouchableOpacity onPress={() => setIsSettingsModalOpen(false)} style={styles.closeModalX}>
                <Text style={{ color: theme.textSecondary, fontSize: 18 }}>✕</Text>
              </TouchableOpacity>
            </View>

            <View style={[styles.settingsTabs, { backgroundColor: theme.bgSecondary }]}>
              <TouchableOpacity
                style={[styles.settingsTab, settingsTab === 'general' && { backgroundColor: theme.accent }]}
                onPress={() => setSettingsTab('general')}
              >
                <Text style={[styles.settingsTabText, { color: settingsTab === 'general' ? '#ffffff' : theme.textSecondary }]}>General</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.settingsTab, settingsTab === 'diagnostics' && { backgroundColor: theme.accent }]}
                onPress={() => setSettingsTab('diagnostics')}
              >
                <Text style={[styles.settingsTabText, { color: settingsTab === 'diagnostics' ? '#ffffff' : theme.textSecondary }]}>Diagnostics</Text>
              </TouchableOpacity>
            </View>

            {settingsTab === 'general' ? (
              <ScrollView style={styles.settingsScroll} contentContainerStyle={styles.settingsContent}>
                <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Theme</Text>
                <View style={[styles.themeSegmentedControl, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
                  {themeModeList.map((mode) => {
                    const isActive = draftSettingsThemeMode === mode.value;
                    return (
                      <TouchableOpacity
                        key={mode.value}
                        style={[styles.themeSegment, isActive && { backgroundColor: theme.accent }]}
                        onPress={() => setDraftSettingsThemeMode(mode.value)}
                      >
                        <Text style={[styles.themeSegmentText, { color: isActive ? '#ffffff' : theme.textSecondary }]}>
                          {mode.desc}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>

                <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Default AI Model</Text>
                {modelsList.map((model) => {
                  const badge = getBadgeStyles(model.value, isDark);
                  const isActive = draftSettingsModel === model.value;
                  return (
                    <TouchableOpacity
                      key={model.value}
                      style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                      onPress={() => {
                        setDraftSettingsModel(model.value);
                        if (!model.supportsUltra && draftSettingsCodexEffort === 'Ultra') {
                          setDraftSettingsCodexEffort('Medium');
                        }
                        if (!model.supportsFast && draftSettingsCodexSpeed === 'Fast') {
                          setDraftSettingsCodexSpeed('Standard');
                        }
                      }}
                    >
                      <View style={styles.modalItemLeft}>
                        <View style={[styles.badge, { backgroundColor: badge.bg }]}>
                          <Text style={[styles.badgeText, { color: badge.color }]}>{badge.text}</Text>
                        </View>
                        <View style={styles.modelInfo}>
                          <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{model.label || model.value}</Text>
                          <Text style={[styles.modelDesc, { color: theme.textSecondary }]} numberOfLines={1}>{model.desc}</Text>
                        </View>
                      </View>
                      {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                    </TouchableOpacity>
                  );
                })}

                {isCodexModel(draftSettingsModel) && (
                  <>
                    <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Codex Effort</Text>
                    {getCodexEfforts(draftSettingsModel).map((item) => {
                      const isActive = draftSettingsCodexEffort === item.value;
                      return (
                        <TouchableOpacity
                          key={item.value}
                          style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                          onPress={() => setDraftSettingsCodexEffort(item.value)}
                        >
                          <View style={styles.modelInfo}>
                            <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{item.value}</Text>
                            <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{item.desc}</Text>
                          </View>
                          {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                        </TouchableOpacity>
                      );
                    })}

                    <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Codex Speed</Text>
                    {getCodexSpeeds(draftSettingsModel).map((item) => {
                      const isActive = draftSettingsCodexSpeed === item.value;
                      return (
                        <TouchableOpacity
                          key={item.value}
                          style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                          onPress={() => setDraftSettingsCodexSpeed(item.value)}
                        >
                          <View style={styles.modelInfo}>
                            <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{item.value}</Text>
                            <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{item.desc}</Text>
                          </View>
                          {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                        </TouchableOpacity>
                      );
                    })}
                  </>
                )}

                {isClaudeModel(draftSettingsModel) && (
                  <>
                    {getModelOption(draftSettingsModel)?.supportsClaudeEffort && (
                      <>
                        <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Claude Effort</Text>
                        {getClaudeEfforts(draftSettingsModel).map((item) => {
                          const isActive = draftSettingsClaudeEffort === item.value;
                          return (
                            <TouchableOpacity
                              key={item.value}
                              style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                              onPress={() => setDraftSettingsClaudeEffort(item.value)}
                            >
                              <View style={styles.modelInfo}>
                                <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{item.value}</Text>
                                <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{item.desc}</Text>
                              </View>
                              {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                            </TouchableOpacity>
                          );
                        })}
                      </>
                    )}

                    <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Claude Thinking</Text>
                    <View
                      style={[
                        styles.settingsToggleRow,
                        { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor },
                      ]}
                    >
                      <View style={styles.modelInfo}>
                        <Text style={[styles.modelName, { color: theme.textPrimary }]}>Thinking</Text>
                        <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>
                          Can think for more complex tasks
                        </Text>
                      </View>
                      <Switch
                        value={getModelOption(draftSettingsModel)?.thinkingRequired
                          ? true
                          : draftSettingsClaudeThinking}
                        onValueChange={setDraftSettingsClaudeThinking}
                        disabled={Boolean(getModelOption(draftSettingsModel)?.thinkingRequired)}
                        trackColor={{ false: theme.borderColor, true: theme.accent }}
                        thumbColor="#ffffff"
                      />
                    </View>
                  </>
                )}

                <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Execution Target</Text>
                {targetsList.map((target) => {
                  const isActive = draftSettingsTarget === target.value;
                  return (
                    <TouchableOpacity
                      key={target.value}
                      style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                      onPress={() => setDraftSettingsTarget(target.value)}
                    >
                      <View style={styles.modelInfo}>
                        <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{target.value}</Text>
                        <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{target.desc}</Text>
                      </View>
                      {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                    </TouchableOpacity>
                  );
                })}

                <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Speech Recognition Language</Text>
                {speechLanguageList.map((language) => {
                  const isActive = draftSettingsSpeechLang === language.value;
                  return (
                    <TouchableOpacity
                      key={language.value}
                      style={[styles.modalItem, isActive && { backgroundColor: theme.bgActive }]}
                      onPress={() => setDraftSettingsSpeechLang(language.value)}
                    >
                      <View style={styles.modelInfo}>
                        <Text style={[styles.modelName, { color: theme.textPrimary }, isActive && { fontWeight: '700' }]}>{language.desc}</Text>
                        <Text style={[styles.modelDesc, { color: theme.textSecondary }]}>{language.value}</Text>
                      </View>
                      {isActive && <Text style={{ color: theme.accent, fontSize: 16, fontWeight: '700' }}>✓</Text>}
                    </TouchableOpacity>
                  );
                })}

                <Text style={[styles.settingsGroupTitle, { color: theme.textSecondary }]}>Chat Font Size</Text>
                <View style={[styles.settingsSliderCard, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
                  <FontSizeSlider
                    value={draftSettingsFontSize}
                    onChange={(val) => setDraftSettingsFontSize(val)}
                    theme={theme}
                  />
                </View>
              </ScrollView>
            ) : (
              <View style={styles.settingsContent}>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Mobile App</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.textPrimary }]}>KookAI Companion</Text>
                </View>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Connection</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.statusGreen }]}>Paired</Text>
                </View>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Current Project</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.textPrimary }]}>{selectedProject}</Text>
                </View>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Model Catalog</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.textPrimary }]}>{modelCatalogVersion}</Text>
                </View>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Theme</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.textPrimary }]}>
                    {selectedThemeMode === 'system' ? `System (${effectiveScheme || 'dark'})` : selectedThemeMode}
                  </Text>
                </View>
                <View style={styles.diagnosticRow}>
                  <Text style={[styles.diagnosticLabel, { color: theme.textSecondary }]}>Conversation</Text>
                  <Text style={[styles.diagnosticValue, { color: theme.textPrimary }]} numberOfLines={1}>
                    {activeConvoId || 'Not started'}
                  </Text>
                </View>
              </View>
            )}

            <View style={[styles.settingsFooter, { borderTopColor: theme.borderColor }]}>
              <TouchableOpacity style={[styles.settingsCancelBtn, { backgroundColor: theme.bgActive }]} onPress={() => setIsSettingsModalOpen(false)}>
                <Text style={[styles.settingsCancelText, { color: theme.textPrimary }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.settingsSaveBtn, { backgroundColor: theme.accent }]} onPress={saveSettings}>
                <Text style={styles.settingsSaveText}>Save Changes</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

 {/* Usage Limits Modal overlay */}
      <Modal visible={isUsageModalOpen} transparent animationType="fade" onRequestClose={closeUsageModal}>
        <View style={styles.popupModalOverlay}>
          <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={closeUsageModal} />
          <View style={[styles.popupCard, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <View style={[styles.popupHeader, { borderBottomColor: theme.borderColor }]}>
              <Text style={[styles.popupTitle, { color: theme.textPrimary }]}>Resource Usage Limits</Text>

              {/* Toggle Switch */}
              <View style={[styles.toggleSwitch, { backgroundColor: theme.bgSecondary }]}>
                <TouchableOpacity
                  style={[styles.toggleBtnOption, usageMode === 'usage' && [styles.toggleBtnActive, { backgroundColor: theme.accent }]]}
                  onPress={() => setUsageMode('usage')}
                >
                  <Text style={[styles.toggleBtnText, usageMode === 'usage' ? { color: '#ffffff' } : { color: theme.textSecondary }]}>Usage</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.toggleBtnOption, usageMode === 'remaining' && [styles.toggleBtnActive, { backgroundColor: theme.accent }]]}
                  onPress={() => setUsageMode('remaining')}
                >
                  <Text style={[styles.toggleBtnText, usageMode === 'remaining' ? { color: '#ffffff' } : { color: theme.textSecondary }]}>Remaining</Text>
                </TouchableOpacity>
              </View>
            </View>

            {usageLimitData ? (
              <>
              <ScrollView style={styles.popupScroll}>
                <View style={styles.usageSection}>
                  <Text style={[styles.usageSectionTitle, { color: theme.accent }]}>
                    {getUsageBucketForModel(selectedModel).title}
                  </Text>
                  {getUsageBucketForModel(selectedModel).note ? (
                    <Text style={[styles.usageRowDesc, styles.usageSectionNote, { color: theme.textMuted }]}>
                      {usageLimitData.codexUsageNote || getUsageBucketForModel(selectedModel).note}
                    </Text>
                  ) : null}
                  {isCodexModel(selectedModel) && usageLimitData.codexRateLimits ? (
                    <>
                      {renderCodexRateLimitRow(usageLimitData.codexRateLimits.primary, 'Weekly Limit')}
                      {renderCodexRateLimitRow(usageLimitData.codexRateLimits.secondary, 'Five Hour Limit')}
                      {typeof usageLimitData.codexRateLimits.availableResets === 'number' ? (
                        <Text style={[styles.usageRowDesc, styles.usageSectionNote, { color: theme.textMuted }]}>
                          {usageLimitData.codexRateLimits.availableResets} available resets
                        </Text>
                      ) : null}
                    </>
                  ) : (
                    <>
                      {renderUsageLimitRow(getUsageBucketForModel(selectedModel).key, 'Weekly', 'Weekly Limit')}
                      {renderUsageLimitRow(getUsageBucketForModel(selectedModel).key, 'Hourly', 'Five Hour Limit')}
                    </>
                  )}
                </View>
              </ScrollView>
              {(loadingUsage || usageLimitError) && (
                <View style={styles.usageStatusRow}>
                  {loadingUsage ? (
                    <>
                      <ActivityIndicator size="small" color={theme.accent} />
                      <Text style={[styles.usageStatusText, { color: theme.textMuted }]}>Refreshing usage data...</Text>
                    </>
                  ) : (
                    <>
                      <Text style={[styles.usageStatusText, { color: theme.textMuted }]}>{usageLimitError}</Text>
                      <TouchableOpacity style={styles.usageRetryBtn} onPress={fetchUsageLimits}>
                        <Text style={[styles.usageRetryText, { color: theme.accent }]}>Retry</Text>
                      </TouchableOpacity>
                    </>
                  )}
                </View>
              )}
              </>
            ) : (
              <Text style={[styles.emptyConvoText, { color: theme.textMuted }]}>Failed to load usage data.</Text>
            )}

            <TouchableOpacity style={[styles.popupCloseBtn, { backgroundColor: theme.bgActive }]} onPress={closeUsageModal}>
              <Text style={[styles.popupCloseBtnText, { color: theme.textPrimary }]}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Toast notification overlay */}
      {toastVisible && (
        <Animated.View
          style={[
            styles.toastContainer,
            {
              backgroundColor: isDark ? 'rgba(34, 38, 48, 0.95)' : 'rgba(255, 255, 255, 0.95)',
              borderColor: theme.borderColor,
              opacity: toastOpacity,
              transform: [{ translateY: toastTranslateY }]
            }
          ]}
        >
          <Text style={{ color: theme.accent, marginRight: 6, fontSize: 14, fontWeight: 'bold' }}>✓</Text>
          <Text style={[styles.toastText, { color: theme.textPrimary }]}>{toastMessage}</Text>
        </Animated.View>
      )}

    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  chatImage: {
    width: '100%',
    height: 180,
    borderRadius: 8,
    marginTop: 4,
    marginBottom: 4,
  },
  videoContainer: {
    width: '100%',
    height: 120,
    borderRadius: 8,
    overflow: 'hidden',
    marginTop: 4,
    marginBottom: 4,
    backgroundColor: '#000000',
  },
  videoPlaceholder: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 12,
  },
  playIcon: {
    fontSize: 28,
    color: '#ffffff',
    marginBottom: 6,
  },
  videoText: {
    fontSize: 12,
    color: '#ffffff',
    textAlign: 'center',
  },
  audioPlayer: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 4,
    marginBottom: 4,
    gap: 12,
  },
  audioPlayButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  audioInfo: {
    flex: 1,
    gap: 4,
  },
  audioTitle: {
    fontSize: 13,
    fontWeight: '600',
  },
  progressBarBg: {
    height: 4,
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 2,
  },
  audioTime: {
    fontSize: 10,
  },
  documentContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 4,
    marginBottom: 4,
    gap: 12,
  },
  documentIcon: {
    fontSize: 24,
  },
  documentName: {
    fontSize: 13,
    fontWeight: '600',
  },
  documentActionText: {
    fontSize: 11,
    fontWeight: '500',
    marginTop: 2,
  },
  recordingPanel: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    width: '100%',
  },
  recordingIndicatorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  recordingDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#ef4444',
  },
  recordingText: {
    fontSize: 14,
    fontWeight: '600',
  },
  stopRecordBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 6,
  },
  stopRecordBtnText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '600',
  },
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  headerLeft: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    minWidth: 0,
  },
  menuBtn: {
    padding: 4,
  },
  headerTitleContainer: {
    flex: 1,
    justifyContent: 'center',
    minWidth: 0,
  },
  headerTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  headerSubtitle: {
    fontSize: 11,
    fontWeight: '600',
    marginTop: 1,
  },
  chatArea: {
    flex: 1,
  },
  messageScroll: {
    flex: 1,
    paddingHorizontal: 16,
  },
  messageContent: {
    paddingVertical: 20,
    gap: 16,
  },
  initializingView: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 120,
    gap: 10,
  },
  initializingTitle: {
    fontSize: 16,
    fontWeight: '700',
  },
  initializingSubtitle: {
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 19,
    paddingHorizontal: 24,
  },
  emptyView: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 80,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 12,
    textAlign: 'center',
  },
  emptySubtitle: {
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 20,
    paddingHorizontal: 20,
  },
  messageBubble: {
    padding: 14,
    borderRadius: 16,
    maxWidth: '85%',
  },
  userBubble: {
    alignSelf: 'flex-end',
    borderTopRightRadius: 4,
  },
  assistantBubble: {
    alignSelf: 'flex-start',
    borderTopLeftRadius: 4,
    borderWidth: 1,
  },
  userText: {
    color: '#ffffff',
    fontSize: 14,
    lineHeight: 20,
  },
  assistantText: {
    fontSize: 14,
    lineHeight: 20,
  },
  stepperCard: {
    alignSelf: 'flex-start',
    maxWidth: '85%',
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    marginVertical: 8,
    width: 290,
  },
  stepperHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
    gap: 8,
  },
  stepperSpinner: {
    marginRight: 4,
  },
  stepperTitle: {
    fontSize: 14,
    fontWeight: '700',
  },
  stepperList: {
    marginTop: 6,
    gap: 12,
  },
  stepItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    minHeight: 36,
  },
  stepIndicatorContainer: {
    width: 20,
    alignItems: 'center',
    marginRight: 10,
    position: 'relative',
    height: '100%',
  },
  completedCheck: {
    width: 16,
    height: 16,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  checkMarkText: {
    color: '#ffffff',
    fontSize: 9,
    fontWeight: 'bold',
  },
  activeDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: '#ffffff',
    zIndex: 1,
  },
  stepLine: {
    position: 'absolute',
    top: 16,
    bottom: -16,
    width: 2,
    left: 9,
  },
  stepContent: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  stepIcon: {
    fontSize: 14,
    marginRight: 4,
  },
  stepText: {
    fontSize: 13,
    lineHeight: 18,
    flex: 1,
  },
  activeStepText: {
    fontWeight: '600',
  },
  completedStepText: {
    fontWeight: '400',
  },
  collapsibleCard: {
    borderWidth: 1,
    borderRadius: 8,
    overflow: 'hidden',
    marginVertical: 4,
    width: '100%',
  },
  collapsibleHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 10,
    gap: 8,
  },
  collapsibleTitle: {
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
  collapsibleBody: {
    padding: 12,
    borderTopWidth: 1,
    borderTopColor: 'rgba(0,0,0,0.05)',
  },
  collapsibleBodyText: {
    fontSize: 12,
    fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
  },
  customSliderContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    width: '100%',
  },
  customSliderValueText: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 10,
  },
  customSliderTrack: {
    height: 6,
    borderRadius: 3,
    position: 'relative',
    justifyContent: 'center',
  },
  customSliderActiveTrack: {
    height: '100%',
    borderRadius: 3,
    position: 'absolute',
    left: 0,
    top: 0,
  },
  customSliderKnob: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    position: 'absolute',
    top: -8,
    marginLeft: -11,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 2.5,
    elevation: 3,
  },
  customSliderLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  customSliderLabelText: {
    fontSize: 11,
  },
  settingsSliderCard: {
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 16,
    width: '100%',
  },
  runningTaskTitle: {
    marginLeft: 4,
  },
  progressLogLine: {
    lineHeight: 18,
  },
queuedPromptBubble: {
    alignSelf: 'flex-end',
    maxWidth: '85%',
    borderWidth: 1,
    borderRadius: 16,
    borderTopRightRadius: 4,
    padding: 12,
    gap: 7,
  },
  queuedPromptHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  queuedPromptStatus: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  queuedPromptCancelBtn: {
    paddingVertical: 3,
    paddingHorizontal: 6,
  },
  queuedPromptCancelText: {
    fontSize: 12,
    fontWeight: '700',
  },
  queuedPromptText: {
    fontSize: 14,
    lineHeight: 20,
  },
  queuedPromptMeta: {
    fontSize: 11,
    fontWeight: '600',
  },
  questionCardContainer: {
    width: '100%',
    alignSelf: 'stretch',
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    marginVertical: 10,
    gap: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 2,
  },
  questionCardDisabled: {
    opacity: 0.65,
  },
  questionTitleText: {
    fontSize: 14.5,
    fontWeight: '500',
    lineHeight: 21,
    marginBottom: 4,
  },
  questionOptionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderRadius: 10,
  },
  questionOptionNum: {
    width: 22,
    height: 22,
    borderRadius: 6,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  questionOptionNumText: {
    fontSize: 11,
    fontWeight: '700',
  },
  questionOptionText: {
    flex: 1,
    fontSize: 13.5,
    lineHeight: 19,
  },
  questionOtherLabel: {
    flexShrink: 0,
    fontSize: 13.5,
  },
  questionOtherInput: {
    flex: 1,
    minWidth: 0,
    fontSize: 13.5,
    paddingVertical: 2,
    borderBottomWidth: 1,
  },
  questionActionsRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: 16,
    marginTop: 6,
  },
  questionSkipBtn: {
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  questionSkipText: {
    fontSize: 13,
    fontWeight: '500',
  },
  questionSubmitBtn: {
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: 8,
  },
  questionSubmitText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '500',
  },
  autocompletePopup: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 6,
    marginBottom: 8,
    maxHeight: 220,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.12,
    shadowRadius: 14,
    elevation: 6,
  },
  autocompleteItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
  },
  autocompleteItemLeft: {
    flex: 1,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  autocompleteSymbol: {
    fontSize: 14,
    fontWeight: '700',
  },
  autocompleteText: {
    fontSize: 13,
    fontWeight: '600',
    flexShrink: 0,
  },
  autocompleteDesc: {
    flex: 1,
    minWidth: 0,
    fontSize: 11,
  },
  autocompleteItemRight: {
    fontSize: 11,
    fontWeight: '600',
  },

  // Prompt Section
  promptSection: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: Platform.OS === 'android' ? 8 : 10,
  },
  promptInputCard: {
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
  },
  promptInputCardDisabled: {
    opacity: 0.72,
  },
  attachmentPreviewContainer: {
    flexDirection: 'row',
    gap: 12,
    paddingTop: 4,
    paddingBottom: 12,
  },
  attachmentThumbnailWrapper: {
    position: 'relative',
    width: 64,
    height: 64,
  },
  attachmentThumbnail: {
    width: 64,
    height: 64,
    borderRadius: 12,
  },
  attachmentDocumentIcon: {
    width: 64,
    height: 64,
    borderRadius: 12,
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 4,
  },
  attachmentDocumentText: {
    fontSize: 8,
    marginTop: 2,
    width: '100%',
    textAlign: 'center',
  },
  attachmentDeleteBtn: {
    position: 'absolute',
    top: -4,
    right: -4,
    backgroundColor: '#000000',
    borderRadius: 10,
    width: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: '#ffffff',
  },
  attachmentDeleteText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: 'bold',
    lineHeight: 14,
    textAlign: 'center',
  },
  promptInputText: {
    fontSize: 14,
    maxHeight: 120,
    minHeight: 40,
    paddingTop: 4,
    paddingBottom: 8,
    textAlignVertical: 'top',
  },
  promptToolRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
  },
  toolRowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  toolRowRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  toolBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
  },
  voiceToolBtn: {
    overflow: 'visible',
  },
  voiceRipple: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
  },
  voiceWaveBars: {
    width: 16,
    height: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
  voiceWaveBar: {
    width: 3,
    height: 13,
    borderRadius: 2,
  },
  modelPickerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    maxWidth: 230,
  },
  modelPickerText: {
    fontSize: 11,
    fontWeight: '600',
    flexShrink: 1,
  },
  codexOptionsRow: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 8,
  },
  codexOptionBtn: {
    flex: 1,
    minHeight: 40,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  codexOptionLabel: {
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  codexOptionValue: {
    fontSize: 12,
    fontWeight: '600',
    marginTop: 2,
  },
  claudeThinkingOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  settingsToggleRow: {
    minHeight: 66,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  sendBtnRound: {
    width: 28,
    height: 28,
    borderRadius: 14,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtnDisabled: {
    opacity: 0.45,
  },
  sendIcon: {
    color: '#ffffff',
    fontSize: 11,
    transform: [{ rotate: '-45deg' }],
    marginTop: -2,
    marginLeft: 2,
  },
promptBottomBar: {
flexDirection: 'row',
justifyContent: 'space-between',
alignItems: 'center',
marginTop: 10,
paddingHorizontal: 4,
},
bottomBarLeft: {
flex: 1,
flexDirection: 'row',
alignItems: 'center',
gap: 10,
minWidth: 0,
},
targetPickerBtn: {
flexDirection: 'row',
alignItems: 'center',
paddingVertical: 4,
},
targetPickerText: {
fontSize: 11,
fontWeight: '600',
},
projectPickerBtn: {
flex: 1,
maxWidth: 140,
flexDirection: 'row',
alignItems: 'center',
paddingVertical: 4,
minWidth: 0,
},
projectPickerText: {
flexShrink: 1,
fontSize: 11,
fontWeight: '600',
},
bottomBarRight: {
flexDirection: 'row',
alignItems: 'center',
gap: 12,
},
  usageBtnCircleContainer: {
    width: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 12,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },

  // Sidebar styles
  sidebarBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
    zIndex: 99,
  },
  sidebarBackdropTouchable: {
    flex: 1,
  },
  sidebar: {
    position: 'absolute',
    top: 0,
    left: 0,
    bottom: 0,
    width: 280,
    borderRightWidth: 1,
    zIndex: 100,
    paddingVertical: 20,
    paddingHorizontal: 16,
    display: 'flex',
    flexDirection: 'column',
  },
  sidebarHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 14,
    borderBottomWidth: 1,
    marginBottom: 16,
  },
  sidebarLogo: {
    fontSize: 16,
    fontWeight: '700',
  },
  closeSidebarBtn: {
    padding: 4,
  },
  newChatBtn: {
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    marginBottom: 16,
  },
  newChatBtnText: {
    color: '#ffffff',
    fontWeight: '600',
    fontSize: 14,
  },
  sidebarScroll: {
    flex: 1,
  },
  sidebarContent: {
    paddingBottom: 20,
  },
  emptyConvoText: {
    fontSize: 13,
    textAlign: 'center',
    marginTop: 20,
  },
  projectGroup: {
    marginBottom: 20,
  },
  projectHeader: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 8,
    paddingHorizontal: 4,
  },
  projectItems: {
    gap: 4,
  },
  sidebarConvoItem: {
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
  },
  sidebarConvoText: {
    fontSize: 13,
  },
  sidebarFooter: {
    borderTopWidth: 1,
    paddingTop: 16,
    paddingBottom: Platform.OS === 'android' ? 44 : 16,
    marginTop: 8,
    gap: 10,
  },
  sidebarSettingsBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
  },
  sidebarSettingsIcon: {
    fontSize: 15,
    fontWeight: '700',
  },
  sidebarSettingsText: {
    fontWeight: '600',
    fontSize: 13,
  },
  sidebarDisconnectBtn: {
    backgroundColor: '#ef4444',
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  sidebarDisconnectText: {
    color: '#ffffff',
    fontWeight: '600',
    fontSize: 13,
  },

  // Modals & Bottom sheets
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  bottomSheet: {
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderTopWidth: 1,
    maxHeight: '60%',
    paddingTop: 16,
    paddingBottom: 30,
  },
  settingsBottomSheet: {
    maxHeight: '78%',
    paddingBottom: 0,
  },
  bottomSheetHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
  },
  bottomSheetTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  closeModalX: {
    padding: 4,
  },
  bottomSheetList: {
    paddingHorizontal: 12,
  },
  bottomSheetContent: {
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  settingsTabs: {
    flexDirection: 'row',
    borderRadius: 10,
    padding: 3,
    marginHorizontal: 20,
    marginTop: 14,
  },
  settingsTab: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  settingsTabText: {
    fontSize: 12,
    fontWeight: '700',
  },
  settingsScroll: {
    flexGrow: 0,
  },
  settingsContent: {
    paddingHorizontal: 12,
    paddingTop: 12,
    paddingBottom: 14,
  },
  settingsGroupTitle: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginTop: 12,
    marginBottom: 4,
    paddingHorizontal: 4,
  },
  themeSegmentedControl: {
    flexDirection: 'row',
    borderWidth: 1,
    borderRadius: 10,
    padding: 3,
    marginBottom: 8,
  },
  themeSegment: {
    flex: 1,
    paddingVertical: 9,
    alignItems: 'center',
    borderRadius: 8,
  },
  themeSegmentText: {
    fontSize: 12,
    fontWeight: '700',
  },
  diagnosticRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 14,
    paddingVertical: 12,
    paddingHorizontal: 8,
  },
  diagnosticLabel: {
    fontSize: 12,
    fontWeight: '600',
  },
  diagnosticValue: {
    flex: 1,
    textAlign: 'right',
    fontSize: 12,
    fontWeight: '700',
  },
  settingsFooter: {
    flexDirection: 'row',
    gap: 10,
    borderTopWidth: 1,
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: Platform.OS === 'android' ? 30 : 22,
  },
  settingsCancelBtn: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  settingsCancelText: {
    fontSize: 13,
    fontWeight: '700',
  },
  settingsSaveBtn: {
    flex: 1.4,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  settingsSaveText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '700',
  },
  modalItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginVertical: 4,
  },
  modalItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    gap: 12,
  },
  contextMenuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
  },
  contextMenuIcon: {
    width: 30,
    height: 30,
    borderRadius: 15,
    textAlign: 'center',
    textAlignVertical: 'center',
    fontSize: 16,
    fontWeight: '700',
  },
  contextMenuTextBlock: {
    flex: 1,
    minWidth: 0,
  },
  contextMenuTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  contextMenuDesc: {
    fontSize: 11,
    lineHeight: 15,
    marginTop: 2,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    alignSelf: 'center',
    minWidth: 50,
    alignItems: 'center',
  },
  badgeText: {
    fontSize: 9,
    fontWeight: '800',
  },
  modelInfo: {
    flex: 1,
  },
  modelName: {
    fontSize: 13,
    fontWeight: '600',
  },
  modelDesc: {
    fontSize: 11,
    marginTop: 2,
  },

  // Popup Modal (Usage Limit Center Box)
  popupModalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  popupCard: {
    width: '85%',
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 5,
    maxHeight: '80%',
  },
  popupHeader: {
    borderBottomWidth: 1,
    paddingBottom: 16,
    marginBottom: 16,
    alignItems: 'center',
    gap: 12,
  },
  popupTitle: {
    fontSize: 16,
    fontWeight: '700',
  },
  toggleSwitch: {
    flexDirection: 'row',
    borderRadius: 10,
    padding: 2,
    width: '100%',
  },
  toggleBtnOption: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  toggleBtnActive: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  toggleBtnText: {
    fontSize: 12,
    fontWeight: '600',
  },
  popupScroll: {
    flexGrow: 0,
  },
  usageErrorState: {
    paddingVertical: 18,
    alignItems: 'center',
  },
  usageStatusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingTop: 12,
  },
  usageStatusText: {
    flexShrink: 1,
    fontSize: 11,
    lineHeight: 15,
    textAlign: 'center',
  },
  usageRetryBtn: {
    paddingVertical: 4,
    paddingHorizontal: 6,
  },
  usageRetryText: {
    fontSize: 12,
    fontWeight: '700',
  },
  usageSection: {
    marginBottom: 10,
  },
  usageSectionTitle: {
    fontSize: 12,
    fontWeight: '800',
    marginBottom: 12,
  },
  usageSectionNote: {
    marginBottom: 8,
    paddingHorizontal: 4,
  },
  usageRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginVertical: 8,
    paddingHorizontal: 4,
  },
  usageRowLabel: {
    flex: 1,
    paddingRight: 10,
  },
  usageRowName: {
    fontSize: 13,
    fontWeight: '600',
  },
  usageRowDesc: {
    fontSize: 11,
    marginTop: 2,
    lineHeight: 14,
  },
  usageRowPercent: {
    fontSize: 14,
    fontWeight: '700',
  },
  popupCloseBtn: {
    marginTop: 20,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    width: '100%',
  },
  popupCloseBtnText: {
    fontWeight: '600',
    fontSize: 14,
  },
  toastContainer: {
    position: 'absolute',
    top: 90,
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 25,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 6,
    elevation: 4,
    zIndex: 9999,
  },
  toastText: {
    fontSize: 13,
    fontWeight: '600',
  },
  themeToggleBtn: {
    padding: 8,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  seeAllBtn: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    alignItems: 'flex-start',
    marginTop: 4,
  },
  seeAllText: {
    fontSize: 12,
    fontWeight: '600',
  }
});
