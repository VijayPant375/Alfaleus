import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Animated,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Linking,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import NetInfo from '@react-native-community/netinfo';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Question = {
  id: number;
  type: 'technical' | 'behavioural' | 'situational';
  question: string;
  time_limit_seconds: number;
};

type ScreenState =
  | 'loading'        // fetching questions
  | 'permissions'    // requesting cam/mic permissions
  | 'permission_denied'
  | 'thinking'       // countdown before question
  | 'question'       // showing question, not yet recording
  | 'recording'      // actively recording
  | 'uploading'      // chunking + uploading
  | 'review'         // review screen before submit
  | 'error';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHUNK_SIZE_BYTES = 2 * 1024 * 1024; // 2 MB
const THINK_TIME_SECONDS = 30;

const TYPE_LABELS: Record<Question['type'], string> = {
  technical: 'Technical',
  behavioural: 'Behavioural',
  situational: 'Situational',
};

const TYPE_COLORS: Record<Question['type'], string> = {
  technical: '#208AEF',
  behavioural: '#9B59B6',
  situational: '#27AE60',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

const MAX_CHUNK_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

async function uploadChunkWithRetry(
  form: FormData,
  apiUrl: string,
  token: string,
  chunkIndex: number,
): Promise<void> {
  let lastError: Error | null = null;
  for (let attempt = 1; attempt <= MAX_CHUNK_RETRIES; attempt++) {
    try {
      const res = await fetch(`${apiUrl}/interview/${token}/upload-chunk`, {
        method: "POST",
        body: form,
      });
      if (res.ok) return;
      lastError = new Error(`Server returned ${res.status}`);
    } catch (e) {
      lastError = e instanceof Error ? e : new Error("Network error");
    }
    if (attempt < MAX_CHUNK_RETRIES) {
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    }
  }
  throw new Error(
    `We couldn't upload part ${chunkIndex + 1} of your answer after ${MAX_CHUNK_RETRIES} attempts. ` +
    `Please check your internet connection and try again. (${lastError?.message})`
  );
}

async function chunkAndUpload(
  fileUri: string,
  token: string,
  questionId: number,
  apiUrl: string,
  onProgress: (msg: string) => void,
): Promise<void> {
  // Fetch the recorded file as a blob
  const res = await fetch(fileUri);
  const blob = await res.blob();
  const totalSize = blob.size;
  const totalChunks = Math.max(1, Math.ceil(totalSize / CHUNK_SIZE_BYTES));

  for (let i = 0; i < totalChunks; i++) {
    onProgress(`Uploading chunk ${i + 1} of ${totalChunks}...`);
    const start = i * CHUNK_SIZE_BYTES;
    const end = Math.min(start + CHUNK_SIZE_BYTES, totalSize);
    const chunkBlob = blob.slice(start, end, 'video/webm');

    const form = new FormData();
    form.append('question_id', String(questionId));
    form.append('chunk_index', String(i));
    form.append('total_chunks', String(totalChunks));
    form.append('video_chunk', {
      uri: fileUri,   // fallback for RN FormData
      name: `chunk_${i}.webm`,
      type: 'video/webm',
    } as any);

    await uploadChunkWithRetry(form, apiUrl, token, i);
  }

  // Finalize
  onProgress('Finalizing answer...');
  const finalRes = await fetch(`${apiUrl}/interview/${token}/finalize-answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_id: questionId, total_chunks: totalChunks }),
  });

  if (!finalRes.ok) {
    throw new Error(`Finalize failed: ${finalRes.status}`);
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuestionsScreen() {
  const { token, candidateName } = useLocalSearchParams<{ token: string; candidateName?: string }>();
  const router = useRouter();

  const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

  // --- Permissions ---
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [micPermission, requestMicPermission] = useMicrophonePermissions();

  // --- Core state ---
  const [screenState, setScreenState] = useState<ScreenState>('loading');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [timeLeft, setTimeLeft] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [answeredSet, setAnsweredSet] = useState<Set<number>>(new Set());

  // --- Refs ---
  const cameraRef = useRef<CameraView>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingRef = useRef(false);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  // ---------------------------------------------------------------------------
  // Fetch questions on mount
  // ---------------------------------------------------------------------------

  const fetchQuestions = useCallback(async () => {
    try {
      setScreenState('loading');
      const res = await fetch(`${API_URL}/interview/${token}/questions`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data: Question[] = await res.json();
      setQuestions(data);
      // After fetching, request permissions
      setScreenState('permissions');
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to load questions.');
      setScreenState('error');
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  // ---------------------------------------------------------------------------
  // Permission flow
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (screenState !== 'permissions') return;
    (async () => {
      const cam = cameraPermission?.granted ? cameraPermission : await requestCameraPermission();
      const mic = micPermission?.granted ? micPermission : await requestMicPermission();
      if (!cam?.granted || !mic?.granted) {
        setScreenState('permission_denied');
      } else {
        setCurrentIndex(0);
        setTimeLeft(THINK_TIME_SECONDS);
        setScreenState('thinking');
      }
    })();
  }, [screenState]);

  // ---------------------------------------------------------------------------
  // Countdown timer
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (screenState === 'thinking') {
      timerRef.current = setInterval(() => {
        setTimeLeft(prev => {
          if (prev <= 1) {
            clearInterval(timerRef.current!);
            setScreenState('question');
            return questions[currentIndex]?.time_limit_seconds ?? 120;
          }
          return prev - 1;
        });
      }, 1000);
      return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }

    if (screenState !== 'recording') {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }
    timerRef.current = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(timerRef.current!);
          handleStopRecording();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [screenState, currentIndex, questions]);

  // ---------------------------------------------------------------------------
  // Pulse animation for REC indicator
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (screenState !== 'recording') {
      pulseAnim.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 0.3, duration: 600, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1, duration: 600, useNativeDriver: true }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [screenState]);

  // ---------------------------------------------------------------------------
  // Recording controls
  // ---------------------------------------------------------------------------

  const handleStartRecording = async () => {
    if (!cameraRef.current || recordingRef.current) return;
    recordingRef.current = true;
    setScreenState('recording');
    try {
      await cameraRef.current.recordAsync({ maxDuration: questions[currentIndex]?.time_limit_seconds ?? 300 });
    } catch (_) {
      // recordAsync rejects when stopRecording is called — expected
    }
  };

  const handleStopRecording = async () => {
    if (!cameraRef.current || !recordingRef.current) return;
    recordingRef.current = false;
    cameraRef.current.stopRecording();
    // onRecordingFinished will handle the upload
  };

  const handleRecordingFinished = async (result: { uri: string }) => {
    if (!result?.uri) return;

    const netInfo = await NetInfo.fetch();
    if (!netInfo.isConnected) {
      setErrorMsg("You appear to be offline. Please reconnect to the internet and tap Retry.");
      setScreenState('error');
      return;
    }

    const question = questions[currentIndex];
    setScreenState('uploading');
    try {
      await chunkAndUpload(result.uri, token, question.id, API_URL, setUploadStatus);
      setAnsweredSet(prev => new Set(prev).add(question.id));
      setScreenState('question'); // show Next/Submit button
      setTimeLeft(questions[currentIndex + 1]?.time_limit_seconds ?? 120);
    } catch (e: any) {
      setErrorMsg(e.message || 'Upload failed.');
      setScreenState('error');
    }
  };

  // ---------------------------------------------------------------------------
  // Navigation between questions
  // ---------------------------------------------------------------------------

  const handleNext = () => {
    const nextIndex = currentIndex + 1;
    if (nextIndex >= questions.length) {
      // All done — transition to review state
      setScreenState('review');
      return;
    }
    setCurrentIndex(nextIndex);
    setTimeLeft(THINK_TIME_SECONDS);
    setScreenState('thinking');
  };

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  const currentQuestion = questions[currentIndex];
  const isAnswered = currentQuestion ? answeredSet.has(currentQuestion.id) : false;
  const isLastQuestion = currentIndex === questions.length - 1;
  const timerColor = timeLeft <= 30 ? '#E74C3C' : timeLeft <= 60 ? '#F39C12' : '#27AE60';

  // ---------------------------------------------------------------------------
  // Screen: Loading
  // ---------------------------------------------------------------------------

  if (screenState === 'loading') {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#208AEF" />
        <Text style={styles.loadingText}>Generating your interview questions...</Text>
      </View>
    );
  }

  // ---------------------------------------------------------------------------
  // Screen: Permission denied
  // ---------------------------------------------------------------------------

  if (screenState === 'permission_denied') {
    return (
      <View style={styles.center}>
        <Text style={styles.permIcon}>🎥</Text>
        <Text style={styles.permTitle}>Camera & Microphone Required</Text>
        <Text style={styles.permBody}>
          To record your interview, Alfaleus needs access to your camera and microphone. Please open your device Settings, find Alfaleus, and enable Camera and Microphone access. Then return to this screen.
        </Text>
        <TouchableOpacity style={{ marginTop: 24, backgroundColor: '#208AEF', paddingHorizontal: 36, paddingVertical: 14, borderRadius: 12 }} onPress={() => Linking.openSettings()}>
          <Text style={styles.retryBtnText}>Open Settings</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // ---------------------------------------------------------------------------
  // Screen: Error
  // ---------------------------------------------------------------------------

  if (screenState === 'error') {
    return (
      <View style={styles.center}>
        <Text style={styles.errorIcon}>⚠️</Text>
        <Text style={styles.errorTitle}>Something went wrong while recording or uploading your answer.</Text>
        <Text style={styles.errorBody}>{errorMsg}</Text>
        <TouchableOpacity style={styles.retryBtn} onPress={fetchQuestions}>
          <Text style={styles.retryBtnText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // ---------------------------------------------------------------------------
  // Screen: Uploading
  // ---------------------------------------------------------------------------

  if (screenState === 'uploading') {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#208AEF" />
        <Text style={styles.uploadText}>{uploadStatus || 'Uploading...'}</Text>
      </View>
    );
  }

  // ---------------------------------------------------------------------------
  // Screen: Review
  // ---------------------------------------------------------------------------

  if (screenState === 'review') {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.timer}>Review Your Interview</Text>
        </View>
        <View style={styles.reviewContainer}>
          {questions.map((q, idx) => {
            const answered = answeredSet.has(q.id);
            return (
              <View key={q.id} style={styles.reviewItem}>
                <Text style={styles.reviewQuestionText} numberOfLines={2}>
                  {idx + 1}. {q.question}
                </Text>
                <View style={[styles.badge, { backgroundColor: answered ? '#27AE6020' : '#7F8C8D20' }]}>
                  <Text style={[styles.badgeText, { color: answered ? '#27AE60' : '#7F8C8D' }]}>
                    {answered ? 'Answered' : 'Not Answered'}
                  </Text>
                </View>
              </View>
            );
          })}
          <TouchableOpacity 
            style={[styles.nextBtn, { marginTop: 24 }]} 
            onPress={() => {
              router.replace(`/interview/${token}/complete?candidateName=${encodeURIComponent(candidateName || '')}`);
            }}
          >
            <Text style={styles.nextBtnText}>✓  Submit Interview</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  // ---------------------------------------------------------------------------
  // Main screen: question + camera
  // ---------------------------------------------------------------------------

  return (
    <View style={styles.container}>
      {/* Header bar */}
      <View style={styles.header}>
        <Text style={styles.counter}>Question {currentIndex + 1} of {questions.length}</Text>
        {screenState === 'recording' && (
          <View style={styles.recRow}>
            <Animated.View style={[styles.recDot, { opacity: pulseAnim }]} />
            <Text style={styles.recLabel}>REC</Text>
          </View>
        )}
        <Text style={[styles.timer, { color: timerColor }]}>{formatTime(timeLeft)}</Text>
      </View>

      {/* Camera preview */}
      <CameraView
        ref={cameraRef}
        style={styles.camera}
        facing="front"
        mode="video"
        onRecordingFinished={handleRecordingFinished}
        onRecordingError={(error) => {
          setErrorMsg(error.message || 'Recording error.');
          setScreenState('error');
        }}
      />

      {/* Question card */}
      <View style={styles.questionCard}>
        {/* Type badge */}
        <View style={[styles.badge, { backgroundColor: TYPE_COLORS[currentQuestion?.type ?? 'technical'] + '20' }]}>
          <Text style={[styles.badgeText, { color: TYPE_COLORS[currentQuestion?.type ?? 'technical'] }]}>
            {TYPE_LABELS[currentQuestion?.type ?? 'technical']}
          </Text>
        </View>

        <Text style={styles.questionText}>{currentQuestion?.question}</Text>

        {screenState === 'thinking' && (
          <View style={styles.thinkingContainer}>
            <Text style={styles.thinkingNumber}>{timeLeft}s</Text>
            <Text style={styles.thinkingLabel}>Think time remaining</Text>
          </View>
        )}

        {/* Controls */}
        <View style={styles.controls}>
          {screenState === 'thinking' ? (
            <TouchableOpacity 
              style={styles.skipBtn} 
              onPress={() => {
                if (timerRef.current) clearInterval(timerRef.current);
                setScreenState('question');
                setTimeLeft(currentQuestion?.time_limit_seconds ?? 120);
              }}
            >
              <Text style={styles.skipBtnText}>Skip & Record Now</Text>
            </TouchableOpacity>
          ) : isAnswered ? (
            // After recording + upload: show Next / Submit
            <TouchableOpacity style={styles.nextBtn} onPress={handleNext}>
              <Text style={styles.nextBtnText}>
                {isLastQuestion ? 'Review Interview →' : 'Next Question →'}
              </Text>
            </TouchableOpacity>
          ) : screenState === 'recording' ? (
            // Recording in progress
            <TouchableOpacity style={styles.stopBtn} onPress={handleStopRecording}>
              <View style={styles.stopIcon} />
              <Text style={styles.stopBtnText}>Stop Recording</Text>
            </TouchableOpacity>
          ) : (
            // Ready to record
            <TouchableOpacity style={styles.startBtn} onPress={handleStartRecording}>
              <View style={styles.recCircle} />
              <Text style={styles.startBtnText}>Start Recording</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0a0a',
    padding: 28,
  },

  // Header
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 12,
    backgroundColor: '#0a0a0a',
  },
  counter: {
    color: '#aaa',
    fontSize: 14,
    fontWeight: '600',
  },
  timer: {
    fontSize: 20,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  recRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  recDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#E74C3C',
  },
  recLabel: {
    color: '#E74C3C',
    fontWeight: '700',
    fontSize: 13,
    letterSpacing: 1,
  },

  // Camera
  camera: {
    flex: 1,
    marginHorizontal: 0,
  },

  // Question card
  questionCard: {
    backgroundColor: '#141414',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 24,
    paddingBottom: 36,
    gap: 16,
  },
  badge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 20,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  questionText: {
    color: '#FFFFFF',
    fontSize: 17,
    lineHeight: 26,
    fontWeight: '500',
  },

  // Controls
  controls: {
    marginTop: 8,
  },
  startBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#E74C3C',
    borderRadius: 14,
    paddingVertical: 16,
    gap: 10,
  },
  recCircle: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: '#fff',
  },
  startBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  stopBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#222',
    borderWidth: 2,
    borderColor: '#E74C3C',
    borderRadius: 14,
    paddingVertical: 16,
    gap: 10,
  },
  stopIcon: {
    width: 14,
    height: 14,
    borderRadius: 2,
    backgroundColor: '#E74C3C',
  },
  stopBtnText: {
    color: '#E74C3C',
    fontSize: 16,
    fontWeight: '700',
  },
  nextBtn: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#208AEF',
    borderRadius: 14,
    paddingVertical: 16,
  },
  nextBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  skipBtn: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#333',
    borderRadius: 14,
    paddingVertical: 16,
  },
  skipBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  thinkingContainer: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  thinkingNumber: {
    color: '#F39C12',
    fontSize: 48,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  thinkingLabel: {
    color: '#aaa',
    fontSize: 14,
    marginTop: 8,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: '600',
  },

  // Review Screen
  reviewContainer: {
    flex: 1,
    padding: 24,
    gap: 16,
  },
  reviewItem: {
    backgroundColor: '#141414',
    padding: 16,
    borderRadius: 12,
    gap: 8,
  },
  reviewQuestionText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '500',
  },

  // Loading / uploading
  loadingText: {
    color: '#aaa',
    fontSize: 15,
    marginTop: 16,
    textAlign: 'center',
  },
  uploadText: {
    color: '#aaa',
    fontSize: 15,
    marginTop: 16,
    textAlign: 'center',
  },

  // Permissions
  permIcon: {
    fontSize: 56,
    marginBottom: 16,
  },
  permTitle: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 12,
  },
  permBody: {
    color: '#aaa',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
  },

  // Error
  errorIcon: {
    fontSize: 56,
    marginBottom: 16,
  },
  errorTitle: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 8,
  },
  errorBody: {
    color: '#aaa',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 24,
  },
  retryBtn: {
    backgroundColor: '#208AEF',
    paddingHorizontal: 36,
    paddingVertical: 14,
    borderRadius: 12,
  },
  retryBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
});
