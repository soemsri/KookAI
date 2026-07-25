import React, { useState, useEffect } from 'react';
import { StyleSheet, View, ActivityIndicator, StatusBar, Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { loadConnection } from './utils/api';
import PairingScreen from './screens/PairingScreen';
import ChatScreen from './screens/ChatScreen';

export default function App() {
  const [isPaired, setIsPaired] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(true);
  const [pairingUrl, setPairingUrl] = useState<string | null>(null);

  const isPairingUrl = (url: string | null) => {
    return Boolean(url && /(?:^(?:kookai|antigravity):\/\/pair|[?&]pin=\d{6})/.test(url));
  };

  // Check connection status on mount
  useEffect(() => {
    (async () => {
      try {
        const initialUrl = await Linking.getInitialURL();
        if (isPairingUrl(initialUrl)) {
          setPairingUrl(initialUrl);
          setIsPaired(false);
          return;
        }

        const info = await loadConnection();
        setIsPaired(info !== null && info.token !== undefined);
      } catch (err) {
        console.error("Failed to load connection data on startup:", err);
        setIsPaired(false);
      } finally {
        setChecking(false);
      }
    })();
  }, []);

  useEffect(() => {
    const subscription = Linking.addEventListener('url', ({ url }) => {
      if (isPairingUrl(url)) {
        setPairingUrl(url);
        setIsPaired(false);
      }
    });

    return () => subscription.remove();
  }, []);

  if (checking) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor="#0f172a" />
        {isPaired ? (
          <ChatScreen onDisconnect={() => setIsPaired(false)} />
        ) : (
          <PairingScreen
            initialPairingData={pairingUrl}
            onPairSuccess={() => {
              setPairingUrl(null);
              setIsPaired(true);
            }}
          />
        )}
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f172a',
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: '#0f172a',
    justifyContent: 'center',
    alignItems: 'center',
  },
});
