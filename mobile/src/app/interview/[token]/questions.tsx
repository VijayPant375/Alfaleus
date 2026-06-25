import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function QuestionsScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Interview in progress</Text>
      <Text style={styles.message}>Questions coming in Day 3!</Text>
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
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#208AEF',
    marginBottom: 10,
  },
  message: {
    fontSize: 18,
    color: '#666',
  },
});
