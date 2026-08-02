import React, { useState } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  Modal,
  ScrollView,
  TextInput,
  Alert,
  ActivityIndicator,
  useColorScheme
} from 'react-native';
import { ServerNode } from '../utils/api';

export interface WorkspaceItem {
  id: string;
  name: string;
  path?: string;
}

interface ServerSwitcherModalProps {
  visible: boolean;
  onClose: () => void;
  activeServer: ServerNode | null;
  savedServers: ServerNode[];
  activeWorkspaceId: string | null;
  workspaces: WorkspaceItem[];
  onSelectServer: (server: ServerNode) => Promise<void> | void;
  onSelectWorkspace: (workspaceId: string) => Promise<void> | void;
  onAddNewServer: () => void;
  onRefreshServers: () => Promise<void> | void;
  onUpdateServerAlias: (serverId: string, newAlias: string) => Promise<void> | void;
  onDeleteServer: (serverId: string) => Promise<void> | void;
  loadingWorkspaces?: boolean;
}

const colors = {
  dark: {
    bgPrimary: '#0f1115',
    bgSecondary: '#181b22',
    bgActive: '#222630',
    bgCard: '#1e222d',
    borderColor: '#2e3543',
    textPrimary: '#f3f4f6',
    textSecondary: '#9ca3af',
    textMuted: '#6b7280',
    accent: '#3b82f6',
    statusGreen: '#34d399',
    statusYellow: '#fbbf24',
    statusRed: '#f87171',
    badgeGreenBg: 'rgba(52, 211, 153, 0.15)',
    badgeYellowBg: 'rgba(251, 191, 36, 0.15)',
    badgeRedBg: 'rgba(248, 113, 113, 0.15)',
  },
  light: {
    bgPrimary: '#f8f9fa',
    bgSecondary: '#ffffff',
    bgActive: '#eaeaea',
    bgCard: '#f1f5f9',
    borderColor: '#e5e7eb',
    textPrimary: '#1f2937',
    textSecondary: '#4b5563',
    textMuted: '#9ca3af',
    accent: '#2563eb',
    statusGreen: '#10b981',
    statusYellow: '#d97706',
    statusRed: '#ef4444',
    badgeGreenBg: 'rgba(16, 185, 129, 0.15)',
    badgeYellowBg: 'rgba(217, 119, 6, 0.15)',
    badgeRedBg: 'rgba(239, 68, 68, 0.15)',
  }
};

export default function ServerSwitcherModal({
  visible,
  onClose,
  activeServer,
  savedServers,
  activeWorkspaceId,
  workspaces,
  onSelectServer,
  onSelectWorkspace,
  onAddNewServer,
  onRefreshServers,
  onUpdateServerAlias,
  onDeleteServer,
  loadingWorkspaces = false,
}: ServerSwitcherModalProps) {
  const scheme = useColorScheme();
  const theme = scheme === 'light' ? colors.light : colors.dark;

  const [editingServer, setEditingServer] = useState<ServerNode | null>(null);
  const [newAlias, setNewAlias] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefreshServers();
    } finally {
      setRefreshing(false);
    }
  };

  const handleEditPress = (server: ServerNode) => {
    setEditingServer(server);
    setNewAlias(server.name);
  };

  const handleSaveAlias = async () => {
    if (editingServer && newAlias.trim()) {
      await onUpdateServerAlias(editingServer.id, newAlias.trim());
      setEditingServer(null);
    }
  };

  const handleDeletePress = (server: ServerNode) => {
    Alert.alert(
      "Unpair Server",
      `Are you sure you want to remove "${server.name}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Unpair",
          style: "destructive",
          onPress: async () => {
            await onDeleteServer(server.id);
          }
        }
      ]
    );
  };

  const renderStatusBadge = (state: 'local' | 'wan' | 'offline', latency?: number) => {
    let color = theme.statusRed;
    let bg = theme.badgeRedBg;
    let label = 'Offline';

    if (state === 'local') {
      color = theme.statusGreen;
      bg = theme.badgeGreenBg;
      label = `LAN${latency ? ` • ${latency}ms` : ''}`;
    } else if (state === 'wan') {
      color = theme.statusYellow;
      bg = theme.badgeYellowBg;
      label = `WAN${latency ? ` • ${latency}ms` : ''}`;
    }

    return (
      <View style={[styles.badgeContainer, { backgroundColor: bg }]}>
        <View style={[styles.statusDot, { backgroundColor: color }]} />
        <Text style={[styles.badgeText, { color }]}>{label}</Text>
      </View>
    );
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        <View style={[styles.container, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor }]}>
          {/* Header */}
          <View style={[styles.header, { borderBottomColor: theme.borderColor }]}>
            <View style={styles.headerTitleGroup}>
              <Text style={[styles.headerTitle, { color: theme.textPrimary }]}>Servers & Workspaces</Text>
              <TouchableOpacity style={styles.refreshBtn} onPress={handleRefresh} disabled={refreshing}>
                {refreshing ? (
                  <ActivityIndicator size="small" color={theme.accent} />
                ) : (
                  <Text style={[styles.refreshBtnText, { color: theme.accent }]}>🔄 Refresh</Text>
                )}
              </TouchableOpacity>
            </View>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Text style={[styles.closeBtnText, { color: theme.textSecondary }]}>✕</Text>
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.body} contentContainerStyle={{ paddingBottom: 30 }}>
            {/* Section 1: Server List */}
            <View style={styles.sectionHeaderGroup}>
              <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>SERVERS ({savedServers.length})</Text>
              <TouchableOpacity
                style={[styles.addServerBtn, { backgroundColor: theme.accent }]}
                onPress={() => {
                  onClose();
                  onAddNewServer();
                }}
              >
                <Text style={styles.addServerBtnText}>+ Add Server</Text>
              </TouchableOpacity>
            </View>

            <View style={styles.serverList}>
              {savedServers.map((server) => {
                const isActive = activeServer?.id === server.id;

                return (
                  <View
                    key={server.id}
                    style={[
                      styles.serverCard,
                      {
                        backgroundColor: isActive ? theme.bgActive : theme.bgCard,
                        borderColor: isActive ? theme.accent : theme.borderColor,
                        borderWidth: isActive ? 2 : 1,
                      }
                    ]}
                  >
                    <TouchableOpacity
                      style={styles.serverCardContent}
                      onPress={() => onSelectServer(server)}
                    >
                      <View style={styles.serverCardHeader}>
                        <View style={styles.serverTitleRow}>
                          <Text style={[styles.serverRadio, { color: isActive ? theme.accent : theme.textMuted }]}>
                            {isActive ? '🔘' : '⚪'}
                          </Text>
                          <Text style={[styles.serverName, { color: theme.textPrimary }]}>{server.name}</Text>
                        </View>
                        {renderStatusBadge(server.connectionState, server.latency)}
                      </View>

                      <View style={styles.serverDetails}>
                        <Text style={[styles.serverInfoText, { color: theme.textSecondary }]}>
                          IP: {server.localIp} | Host: {server.hostId.substring(0, 10)}...
                        </Text>
                      </View>
                    </TouchableOpacity>

                    {/* Server Action Buttons */}
                    <View style={[styles.serverActionsRow, { borderTopColor: theme.borderColor }]}>
                      <TouchableOpacity
                        style={styles.actionItemBtn}
                        onPress={() => handleEditPress(server)}
                      >
                        <Text style={[styles.actionItemText, { color: theme.textSecondary }]}>✏️ Edit Alias</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={styles.actionItemBtn}
                        onPress={() => handleDeletePress(server)}
                      >
                        <Text style={[styles.actionItemText, { color: theme.statusRed }]}>🗑️ Unpair</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                );
              })}
            </View>

            {/* Section 2: Workspaces of Active Server */}
            <View style={[styles.sectionHeaderGroup, { marginTop: 24 }]}>
              <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>
                WORKSPACES {activeServer ? `(${activeServer.name})` : ''}
              </Text>
            </View>

            {loadingWorkspaces ? (
              <View style={styles.workspaceLoadingContainer}>
                <ActivityIndicator size="small" color={theme.accent} />
                <Text style={[styles.loadingText, { color: theme.textSecondary }]}>Loading workspaces...</Text>
              </View>
            ) : workspaces.length === 0 ? (
              <View style={[styles.emptyContainer, { backgroundColor: theme.bgCard, borderColor: theme.borderColor }]}>
                <Text style={[styles.emptyText, { color: theme.textMuted }]}>
                  {activeServer ? 'No workspaces found on this server.' : 'Select a server to view workspaces.'}
                </Text>
              </View>
            ) : (
              <View style={styles.workspaceList}>
                {workspaces.map((ws) => {
                  const isWsActive = activeWorkspaceId === ws.id;

                  return (
                    <TouchableOpacity
                      key={ws.id}
                      style={[
                        styles.workspaceItem,
                        {
                          backgroundColor: isWsActive ? theme.bgActive : theme.bgCard,
                          borderColor: isWsActive ? theme.accent : theme.borderColor,
                          borderWidth: isWsActive ? 2 : 1,
                        }
                      ]}
                      onPress={() => onSelectWorkspace(ws.id)}
                    >
                      <View style={styles.workspaceRow}>
                        <Text style={[styles.workspaceIcon, { color: isWsActive ? theme.accent : theme.textSecondary }]}>
                          📁
                        </Text>
                        <View style={styles.workspaceTextContainer}>
                          <Text style={[styles.workspaceName, { color: theme.textPrimary, fontWeight: isWsActive ? '700' : '500' }]}>
                            {ws.name}
                          </Text>
                          {ws.path && (
                            <Text style={[styles.workspacePath, { color: theme.textMuted }]} numberOfLines={1}>
                              {ws.path}
                            </Text>
                          )}
                        </View>
                        {isWsActive && (
                          <Text style={[styles.activeCheckmark, { color: theme.accent }]}>✓ Active</Text>
                        )}
                      </View>
                    </TouchableOpacity>
                  );
                })}
              </View>
            )}
          </ScrollView>
        </View>

        {/* Edit Alias Modal */}
        <Modal
          visible={Boolean(editingServer)}
          transparent
          animationType="fade"
          onRequestClose={() => setEditingServer(null)}
        >
          <View style={styles.subModalOverlay}>
            <View style={[styles.subModalCard, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
              <Text style={[styles.subModalTitle, { color: theme.textPrimary }]}>Edit Server Alias</Text>
              <TextInput
                style={[styles.subModalInput, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor, color: theme.textPrimary }]}
                value={newAlias}
                onChangeText={setNewAlias}
                placeholder="Server Alias Name"
                placeholderTextColor={theme.textMuted}
                autoFocus
              />
              <View style={styles.subModalBtnGroup}>
                <TouchableOpacity
                  style={[styles.subModalBtn, { borderColor: theme.borderColor }]}
                  onPress={() => setEditingServer(null)}
                >
                  <Text style={[styles.subModalBtnText, { color: theme.textSecondary }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.subModalBtn, { backgroundColor: theme.accent }]}
                  onPress={handleSaveAlias}
                >
                  <Text style={[styles.subModalBtnText, { color: '#ffffff' }]}>Save</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'flex-end',
  },
  container: {
    maxHeight: '85%',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 16,
    borderBottomWidth: 1,
  },
  headerTitleGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: '700',
  },
  refreshBtn: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  refreshBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },
  closeBtn: {
    padding: 6,
  },
  closeBtnText: {
    fontSize: 22,
    fontWeight: '600',
  },
  body: {
    marginTop: 16,
  },
  sectionHeaderGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
  },
  addServerBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  addServerBtnText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  serverList: {
    gap: 10,
  },
  serverCard: {
    borderRadius: 14,
    overflow: 'hidden',
  },
  serverCardContent: {
    padding: 14,
  },
  serverCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  serverTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  serverRadio: {
    fontSize: 16,
  },
  serverName: {
    fontSize: 16,
    fontWeight: '700',
  },
  serverDetails: {
    paddingLeft: 26,
  },
  serverInfoText: {
    fontSize: 12,
  },
  badgeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 6,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  serverActionsRow: {
    flexDirection: 'row',
    borderTopWidth: 1,
  },
  actionItemBtn: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
  },
  actionItemText: {
    fontSize: 12,
    fontWeight: '600',
  },
  workspaceLoadingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 16,
  },
  loadingText: {
    fontSize: 14,
  },
  emptyContainer: {
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 13,
  },
  workspaceList: {
    gap: 8,
  },
  workspaceItem: {
    borderRadius: 12,
    padding: 14,
  },
  workspaceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  workspaceIcon: {
    fontSize: 18,
  },
  workspaceTextContainer: {
    flex: 1,
  },
  workspaceName: {
    fontSize: 14,
  },
  workspacePath: {
    fontSize: 11,
    marginTop: 2,
  },
  activeCheckmark: {
    fontSize: 12,
    fontWeight: '700',
  },
  subModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  subModalCard: {
    width: '100%',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
  },
  subModalTitle: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 14,
  },
  subModalInput: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    fontSize: 15,
    marginBottom: 16,
  },
  subModalBtnGroup: {
    flexDirection: 'row',
    gap: 10,
  },
  subModalBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
    borderWidth: 1,
  },
  subModalBtnText: {
    fontSize: 14,
    fontWeight: '600',
  }
});
