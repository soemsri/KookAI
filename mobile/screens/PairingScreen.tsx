import React, { useState, useEffect, useRef } from 'react';
import { StyleSheet, Text, View, TextInput, TouchableOpacity, ActivityIndicator, Alert, SafeAreaView, Platform, StatusBar, useColorScheme, Linking, Modal } from 'react-native';
import { Camera, CameraView } from 'expo-camera';
import * as SecureStore from 'expo-secure-store';
import { saveServer, getSavedServers, ServerNode } from '../utils/api';

const WORKER_BASE_URL = "https://antigravity-pairing-broker.rangsarn.workers.dev"; // Central resolver URL

interface PairingScreenProps {
  onPairSuccess: () => void;
  onCancel?: () => void;
  initialPairingData?: string | null;
}

interface PendingPairData {
  hostId: string;
  url: string;
  localIp: string;
  token: string;
  defaultName: string;
  existingServer?: ServerNode;
}

const colors = {
  dark: {
    bgPrimary: '#0f1115',     // Sidebar background
    bgSecondary: '#181b22',   // Chat panel background
    bgActive: '#222630',
    bgInput: '#22262f',
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

export default function PairingScreen({ onPairSuccess, onCancel, initialPairingData }: PairingScreenProps) {
  const scheme = useColorScheme();
  const theme = scheme === 'light' ? colors.light : colors.dark;

  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [scanning, setScanning] = useState(false);
  const [aliasModalVisible, setAliasModalVisible] = useState(false);
  const [serverAlias, setServerAlias] = useState('');
  const [pendingPair, setPendingPair] = useState<PendingPairData | null>(null);

  const lastHandledPairingDataRef = useRef<string | null>(null);

  // Request camera permission on load
  useEffect(() => {
    (async () => {
      const { status } = await Camera.requestCameraPermissionsAsync();
      setHasPermission(status === 'granted');
    })();
  }, []);

  const completePairing = async (pairInfo: PendingPairData, aliasName: string) => {
    try {
      const serverNode: ServerNode = {
        id: pairInfo.existingServer?.id || pairInfo.hostId || `server_${Date.now()}`,
        name: aliasName.trim() || pairInfo.defaultName,
        hostId: pairInfo.hostId,
        url: pairInfo.url,
        localIp: pairInfo.localIp,
        port: 8080,
        token: pairInfo.token,
        createdAt: pairInfo.existingServer?.createdAt || Date.now(),
        lastActive: Date.now(),
        connectionState: 'offline',
      };

      await saveServer(serverNode, true);
      setAliasModalVisible(false);
      setPendingPair(null);
      Alert.alert("Success", `Successfully paired server "${serverNode.name}"!`);
      onPairSuccess();
    } catch (err: any) {
      Alert.alert("Pairing Error", err.message || "Failed to save server.");
    }
  };

  const handlePairWithPin = async (enteredPin: string) => {
    if (enteredPin.length !== 6) {
      Alert.alert("Invalid PIN", "Please enter a 6-digit PIN code.");
      return;
    }

    setLoading(true);
    try {
      // 1. Resolve PIN via Worker Registry
      const resolveRes = await fetch(`${WORKER_BASE_URL}/resolve-pin/${enteredPin}`);
      if (!resolveRes.ok) {
        throw new Error("Expired or invalid PIN code");
      }

      const hostInfo = await resolveRes.json();
      const { host_id, url: desktopUrl, local_ip } = hostInfo;

      // 2. Generate unique device ID
      let deviceUuid = await SecureStore.getItemAsync('device_uuid');
      if (!deviceUuid) {
        deviceUuid = 'dev_' + Math.random().toString(36).substring(2, 10) + Date.now().toString(36);
        await SecureStore.setItemAsync('device_uuid', deviceUuid);
      }

      // 3. Initiate pair handshake to Desktop
      let response;
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000); // 2s timeout
        response = await fetch(`http://${local_ip}:8080/api/pair`, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Bypass-Tunnel-Reminder': 'true'
          },
          body: JSON.stringify({ device_name: "Mobile App Companion", pin: enteredPin, device_uuid: deviceUuid }),
          signal: controller.signal
        });
        clearTimeout(timeoutId);
      } catch {
        // Fallback to public WAN
        response = await fetch(`${desktopUrl}/api/pair`, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Bypass-Tunnel-Reminder': 'true'
          },
          body: JSON.stringify({ device_name: "Mobile App Companion", pin: enteredPin, device_uuid: deviceUuid })
        });
      }

      if (!response.ok) {
        throw new Error("Pairing rejected by host server");
      }

      const pairData = await response.json();
      const { token } = pairData;

      // Check for duplicate host
      const existingServers = await getSavedServers();
      const existing = existingServers.find(s => s.hostId === host_id);
      const defaultName = existing ? existing.name : `Host-${host_id.substring(0, 6)}`;

      const pairInfo: PendingPairData = {
        hostId: host_id,
        url: desktopUrl,
        localIp: local_ip,
        token,
        defaultName,
        existingServer: existing
      };

      if (existing) {
        // Prompt for duplicate host
        Alert.alert(
          "Server Already Paired",
          `A server with Host ID "${host_id}" is already in your saved list as "${existing.name}". Would you like to update its connection details?`,
          [
            { text: "Cancel", style: "cancel", onPress: () => setLoading(false) },
            {
              text: "Update Connection",
              onPress: () => {
                void completePairing(pairInfo, existing.name);
              }
            }
          ]
        );
      } else {
        // Show alias modal for new server
        setPendingPair(pairInfo);
        setServerAlias(defaultName);
        setAliasModalVisible(true);
      }

    } catch (err: any) {
      Alert.alert("Pairing Failed", err.message || "Failed to pair.");
    } finally {
      setLoading(false);
    }
  };

  const extractPairingPin = (data: string): string | null => {
    const trimmed = data.trim();
    if (/^\d{6}$/.test(trimmed)) return trimmed;

    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed.pin === 'string' && /^\d{6}$/.test(parsed.pin)) {
        return parsed.pin;
      }
    } catch {
      // Continue with URL/deep-link parsing below.
    }

    const queryMatch = trimmed.match(/[?&]pin=(\d{6})(?:&|$)/);
    if (queryMatch) return queryMatch[1];

    const pathMatch = trimmed.match(/(?:^|\/)(\d{6})(?:\D*$|$)/);
    return pathMatch ? pathMatch[1] : null;
  };

  const handlePairingData = (data: string, invalidTitle = "Invalid QR") => {
    if (lastHandledPairingDataRef.current === data) return;

    const pairingPin = extractPairingPin(data);
    if (!pairingPin) {
      Alert.alert(invalidTitle, "Could not find a valid 6-digit pairing PIN.");
      return;
    }

    lastHandledPairingDataRef.current = data;
    setPin(pairingPin);
    void handlePairWithPin(pairingPin);
  };

  useEffect(() => {
    if (initialPairingData) {
      handlePairingData(initialPairingData, "Invalid Pairing Link");
    }
  }, [initialPairingData]);

  useEffect(() => {
    const handleUrl = ({ url }: { url: string }) => {
      handlePairingData(url, "Invalid Pairing Link");
    };

    const subscription = Linking.addEventListener('url', handleUrl);

    Linking.getInitialURL()
      .then((url) => {
        if (url) handlePairingData(url, "Invalid Pairing Link");
      })
      .catch((err) => console.error("Failed to read initial pairing link:", err));

    return () => subscription.remove();
  }, []);

  const handleBarCodeScanned = ({ data }: { data: string }) => {
    setScanning(false);
    handlePairingData(data);
  };

  const openNativeScanner = async () => {
    if (hasPermission === false) {
      Alert.alert("No Camera Permission", "Please enable camera access in system settings.");
      return;
    }

    if (!CameraView.isModernBarcodeScannerAvailable) {
      setScanning(true);
      return;
    }

    const subscription = CameraView.onModernBarcodeScanned(({ data }: { data: string }) => {
      subscription.remove();
      void CameraView.dismissScanner().catch(() => {});
      handlePairingData(data);
    });

    try {
      await CameraView.launchScanner({ barcodeTypes: ['qr'] });
    } catch (err) {
      subscription.remove();
      console.error("Failed to launch native QR scanner:", err);
      setScanning(true);
    }
  };

  if (scanning && hasPermission) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.bgSecondary }]}>
        <View style={styles.scannerHeader}>
          <Text style={[styles.title, { color: '#ffffff' }]}>Scan Pairing QR Code</Text>
          <Text style={[styles.subtitle, { color: '#94a3b8' }]}>Point your camera at the desktop pairing QR code.</Text>
        </View>
        
        <CameraView
          style={StyleSheet.absoluteFill}
          onBarcodeScanned={handleBarCodeScanned}
          barcodeScannerSettings={{
            barcodeTypes: ["qr"],
          }}
        />

        <TouchableOpacity style={styles.cancelBtn} onPress={() => setScanning(false)}>
          <Text style={styles.cancelText}>Cancel</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.bgSecondary }]}>
      <StatusBar barStyle={scheme === 'light' ? 'dark-content' : 'light-content'} backgroundColor={theme.bgPrimary} />
      
      {onCancel && (
        <TouchableOpacity style={styles.topBackBtn} onPress={onCancel}>
          <Text style={[styles.topBackBtnText, { color: theme.accent }]}>✕ Close</Text>
        </TouchableOpacity>
      )}

      <View style={[styles.card, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
        <Text style={[styles.logoText, { color: theme.accent }]}>{'\u25B2'} KookAI</Text>
        <Text style={[styles.title, { color: theme.textPrimary }]}>Link New Server</Text>
        <Text style={[styles.subtitle, { color: theme.textSecondary }]}>Enter the 6-digit PIN code or scan the pairing QR code from your desktop app.</Text>

        <TextInput
          style={[styles.input, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor, color: theme.accent }]}
          placeholder="0 0 0 0 0 0"
          placeholderTextColor={theme.textMuted}
          keyboardType="numeric"
          maxLength={6}
          value={pin}
          onChangeText={(val) => {
            setPin(val);
            if (val.length === 6) {
              handlePairWithPin(val);
            }
          }}
        />

        {loading ? (
          <ActivityIndicator size="large" color={theme.accent} style={{ marginVertical: 20 }} />
        ) : (
          <View style={styles.buttonGroup}>
            <TouchableOpacity 
              style={[styles.primaryBtn, { backgroundColor: theme.accent }]} 
              onPress={() => handlePairWithPin(pin)}
            >
              <Text style={styles.primaryBtnText}>Connect via PIN</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={[styles.secondaryBtn, { borderColor: theme.borderColor }]} 
              onPress={() => void openNativeScanner()}
            >
              <Text style={[styles.secondaryBtnText, { color: theme.textSecondary }]}>Scan QR Code</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Task 3.2: Modal to set Server Alias Name */}
      <Modal
        visible={aliasModalVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setAliasModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { backgroundColor: theme.bgPrimary, borderColor: theme.borderColor }]}>
            <Text style={[styles.modalTitle, { color: theme.textPrimary }]}>Name Your Server</Text>
            <Text style={[styles.modalSubtitle, { color: theme.textSecondary }]}>
              Give this server a friendly name (e.g. Office Desktop, Home Mac).
            </Text>

            <TextInput
              style={[styles.modalInput, { backgroundColor: theme.bgSecondary, borderColor: theme.borderColor, color: theme.textPrimary }]}
              placeholder="e.g. Office PC"
              placeholderTextColor={theme.textMuted}
              value={serverAlias}
              onChangeText={setServerAlias}
              autoFocus
            />

            <View style={styles.modalButtonGroup}>
              <TouchableOpacity
                style={[styles.modalSecondaryBtn, { borderColor: theme.borderColor }]}
                onPress={() => {
                  if (pendingPair) {
                    void completePairing(pendingPair, pendingPair.defaultName);
                  }
                }}
              >
                <Text style={[styles.modalSecondaryBtnText, { color: theme.textSecondary }]}>Use Default</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.modalPrimaryBtn, { backgroundColor: theme.accent }]}
                onPress={() => {
                  if (pendingPair) {
                    void completePairing(pendingPair, serverAlias);
                  }
                }}
              >
                <Text style={styles.modalPrimaryBtnText}>Save & Connect</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight : 0,
    paddingBottom: Platform.OS === 'android' ? 44 : 0,
  },
  topBackBtn: {
    position: 'absolute',
    top: 50,
    right: 20,
    zIndex: 10,
    padding: 10,
  },
  topBackBtnText: {
    fontSize: 16,
    fontWeight: '600',
  },
  card: {
    width: '90%',
    borderRadius: 20,
    padding: 30,
    alignItems: 'center',
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 5,
  },
  logoText: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 20,
    letterSpacing: -0.5,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 30,
    lineHeight: 18,
  },
  input: {
    width: '100%',
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    fontSize: 28,
    fontWeight: '700',
    textAlign: 'center',
    letterSpacing: 8,
    marginBottom: 24,
  },
  buttonGroup: {
    width: '100%',
    gap: 12,
  },
  primaryBtn: {
    width: '100%',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  primaryBtnText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '600',
  },
  secondaryBtn: {
    width: '100%',
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  secondaryBtnText: {
    fontSize: 15,
    fontWeight: '600',
  },
  scannerHeader: {
    position: 'absolute',
    top: 50,
    left: 20,
    right: 20,
    zIndex: 10,
    alignItems: 'center',
    backgroundColor: 'rgba(15, 23, 42, 0.8)',
    borderRadius: 12,
    padding: 15,
  },
  cancelBtn: {
    position: 'absolute',
    bottom: 50,
    zIndex: 10,
    backgroundColor: '#ef4444',
    paddingHorizontal: 30,
    paddingVertical: 15,
    borderRadius: 30,
  },
  cancelText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '600',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    width: '100%',
    borderRadius: 20,
    padding: 24,
    borderWidth: 1,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 6,
    textAlign: 'center',
  },
  modalSubtitle: {
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 20,
    lineHeight: 18,
  },
  modalInput: {
    width: '100%',
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    marginBottom: 20,
  },
  modalButtonGroup: {
    flexDirection: 'row',
    gap: 12,
  },
  modalSecondaryBtn: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
  },
  modalSecondaryBtnText: {
    fontSize: 14,
    fontWeight: '600',
  },
  modalPrimaryBtn: {
    flex: 1,
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
  },
  modalPrimaryBtnText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '600',
  }
});
