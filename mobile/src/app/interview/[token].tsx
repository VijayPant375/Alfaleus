import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, Alert } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

type InterviewStatus = {
  candidate_name: string | null;
  job_title: string;
  interview_status: string;
};

export default function InterviewLandingScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusData, setStatusData] = useState<InterviewStatus | null>(null);

  const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchInterviewStatus();
  }, [token]);

  const fetchInterviewStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${API_URL}/interview/${token}`);
      
      if (!res.ok) {
        if (res.status === 404) {
          setError('Invalid or expired interview token');
        } else {
          setError('An error occurred while fetching your interview details.');
        }
        return;
      }
      
      const data = await res.json();
      setStatusData(data);
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleStartInterview = async () => {
    try {
      setStarting(true);
      const res = await fetch(`${API_URL}/interview/${token}/start`, {
        method: 'POST',
      });
      
      if (!res.ok) {
        Alert.alert('Error', 'Failed to start interview. Please try again.');
        return;
      }
      
      // Navigate to questions screen
      router.push(`/interview/${token}/questions`);
    } catch (err) {
      Alert.alert('Error', 'Network error. Please try again.');
    } finally {
      setStarting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color="#208AEF" />
        <Text style={styles.loadingText}>Loading your interview...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Text style={styles.errorText}>{error}</Text>
        <TouchableOpacity style={styles.button} onPress={fetchInterviewStatus}>
          <Text style={styles.buttonText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!statusData) return null;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Interview Details</Text>
      
      <View style={styles.card}>
        <Text style={styles.label}>Candidate:</Text>
        <Text style={styles.value}>{statusData.candidate_name || 'Candidate'}</Text>
        
        <Text style={styles.label}>Role:</Text>
        <Text style={styles.value}>{statusData.job_title}</Text>
        
        <Text style={styles.label}>Status:</Text>
        <Text style={styles.value}>{statusData.interview_status.replace('_', ' ')}</Text>
      </View>
      
      <TouchableOpacity 
        style={[styles.button, starting && styles.buttonDisabled]} 
        onPress={handleStartInterview}
        disabled={starting}
      >
        {starting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Begin Interview</Text>
        )}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    backgroundColor: '#f5f5f5',
  },
  container: {
    flex: 1,
    padding: 20,
    backgroundColor: '#f5f5f5',
    justifyContent: 'center',
  },
  loadingText: {
    marginTop: 10,
    fontSize: 16,
    color: '#666',
  },
  errorText: {
    fontSize: 18,
    color: '#e74c3c',
    textAlign: 'center',
    marginBottom: 20,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#333',
    marginBottom: 30,
    textAlign: 'center',
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 10,
    padding: 20,
    marginBottom: 30,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  label: {
    fontSize: 14,
    color: '#888',
    marginBottom: 4,
  },
  value: {
    fontSize: 18,
    color: '#333',
    fontWeight: '600',
    marginBottom: 16,
  },
  button: {
    backgroundColor: '#208AEF',
    paddingVertical: 15,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonDisabled: {
    backgroundColor: '#90c5f7',
  },
  buttonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
});
