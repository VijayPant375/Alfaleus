import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';

export default function CompleteScreen() {
  const { candidateName } = useLocalSearchParams<{ candidateName?: string }>();

  const displayName = candidateName?.trim() || 'Candidate';

  return (
    <View style={styles.container}>
      <Text style={styles.checkmark}>✓</Text>

      <Text style={styles.title}>Interview Complete</Text>

      <Text style={styles.message}>
        Thank you, <Text style={styles.name}>{displayName}</Text>.{'\n'}
        Your responses have been submitted.
      </Text>

      <Text style={styles.subtext}>
        Our team will review your interview and be in touch soon.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  checkmark: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#27AE6020',
    textAlign: 'center',
    textAlignVertical: 'center',
    lineHeight: 80,
    fontSize: 40,
    color: '#27AE60',
    marginBottom: 28,
    overflow: 'hidden',
  },
  title: {
    color: '#FFFFFF',
    fontSize: 28,
    fontWeight: '700',
    marginBottom: 16,
    textAlign: 'center',
  },
  message: {
    color: '#cccccc',
    fontSize: 17,
    lineHeight: 26,
    textAlign: 'center',
    marginBottom: 20,
  },
  name: {
    color: '#208AEF',
    fontWeight: '700',
  },
  subtext: {
    color: '#666',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
  },
});
