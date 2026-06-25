import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function IndexScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.logo}>Alfaleus</Text>
      <Text style={styles.message}>You've been invited to interview!</Text>
      <Text style={styles.subtext}>Please use the link in your email to begin your interview.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    backgroundColor: '#fff',
  },
  logo: {
    fontSize: 48,
    fontWeight: 'bold',
    color: '#208AEF',
    marginBottom: 20,
  },
  message: {
    fontSize: 20,
    textAlign: 'center',
    fontWeight: '600',
    marginBottom: 10,
  },
  subtext: {
    fontSize: 16,
    textAlign: 'center',
    color: '#666',
  },
});
