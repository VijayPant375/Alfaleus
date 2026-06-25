import { Stack } from 'expo-router';

export default function RootLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Alfaleus' }} />
      <Stack.Screen name="interview/[token]" options={{ title: 'Interview' }} />
      <Stack.Screen name="interview/[token]/questions" options={{ title: 'Questions' }} />
    </Stack>
  );
}
