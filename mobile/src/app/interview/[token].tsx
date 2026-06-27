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
        if (res.status === 410) {
          setError('This interview link has expired. Please contact the recruiter for a new link.');
        } else if (res.status === 404) {
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
      
      // Navigate to questions screen, passing candidate name for the completion screen
      router.push(`/interview/${token}/questions?candidateName=${encodeURIComponent(statusData?.candidate_name || '')}`);
    } catch (err) {
      Alert.alert('Error', 'Network error. Please try again.');
    } finally {
      setStarting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color="#fff" />
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
      <Text style={styles.logo}>Alfaleus</Text>
      
      <View style={styles.headerBox}>
        <Text style={styles.candidateName}>{statusData.candidate_name || 'Candidate'}</Text>
        <Text style={styles.jobTitle}>{statusData.job_title}</Text>
      </View>
      
      <View style={styles.explainerBox}>
        <View style={styles.listItem}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.listText}>5 questions tailored to your profile and the role</Text>
        </View>
        <View style={styles.listItem}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.listText}>30 seconds to think before each recording begins</Text>
        </View>
        <View style={styles.listItem}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.listText}>Up to 3 minutes to record each answer</Text>
        </View>
        <View style={styles.listItem}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.listText}>Once submitted, answers cannot be re-recorded</Text>
        </View>
        <View style={styles.listItem}>
          <Text style={styles.bullet}>•</Text>
          <Text style={styles.listText}>Your recording uploads automatically — if you lose connection, you can resume where you left off</Text>
        </View>
      </View>
      
      <TouchableOpacity 
        style={[styles.button, starting && styles.buttonDisabled]} 
        onPress={handleStartInterview}
        disabled={starting}
      >
        {starting ? (
          <ActivityIndicator color="#0a0a0a" />
        ) : (
          <Text style={styles.buttonText}>Begin Interview</Text>
        )}
      </TouchableOpacity>
      
      <Text style={styles.footerMutedText}>
        Make sure you are in a quiet place with good lighting before you begin.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    backgroundColor: '#0a0a0a',
  },
  container: {
    flex: 1,
    padding: 24,
    backgroundColor: '#0a0a0a',
    justifyContent: 'center',
  },
  loadingText: {
    marginTop: 12,
    fontSize: 16,
    color: '#a0a0a0',
  },
  errorText: {
    fontSize: 16,
    color: '#ef4444',
    textAlign: 'center',
    marginBottom: 20,
  },
  logo: {
    fontSize: 24,
    fontWeight: '700',
    color: '#fff',
    marginBottom: 32,
    textAlign: 'center',
    letterSpacing: 1,
  },
  headerBox: {
    marginBottom: 32,
    alignItems: 'center',
  },
  candidateName: {
    fontSize: 28,
    color: '#fff',
    fontWeight: '600',
    marginBottom: 8,
    textAlign: 'center',
  },
  jobTitle: {
    fontSize: 18,
    color: '#a0a0a0',
    textAlign: 'center',
  },
  explainerBox: {
    marginBottom: 40,
    backgroundColor: '#141414',
    padding: 20,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#222',
  },
  listItem: {
    flexDirection: 'row',
    marginBottom: 16,
    alignItems: 'flex-start',
  },
  bullet: {
    color: '#a0a0a0',
    fontSize: 18,
    marginRight: 12,
    lineHeight: 22,
  },
  listText: {
    color: '#e0e0e0',
    fontSize: 15,
    lineHeight: 22,
    flex: 1,
  },
  button: {
    backgroundColor: '#fff',
    paddingVertical: 16,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 20,
  },
  buttonDisabled: {
    opacity: 0.7,
  },
  buttonText: {
    color: '#0a0a0a',
    fontSize: 18,
    fontWeight: '600',
  },
  footerMutedText: {
    color: '#666',
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 18,
  },
});
