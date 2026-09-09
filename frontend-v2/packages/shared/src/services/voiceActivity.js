export const AVATAR_SILENCE_MS = 5_000
export const AUTO_SEND_REVIEW_MS = 3_000
export const VOICE_RMS_THRESHOLD = 0.025

export function normalizeVoiceLevel(rms, floor = 0.006, ceiling = 0.16) {
  const value = Number(rms)
  if (!Number.isFinite(value) || value <= floor) return 0
  if (ceiling <= floor || value >= ceiling) return 1
  return (value - floor) / (ceiling - floor)
}

export function rootMeanSquare(samples) {
  if (!samples?.length) return 0
  let sum = 0
  for (const sample of samples) {
    const centered = sample / 128 - 1
    sum += centered * centered
  }
  return Math.sqrt(sum / samples.length)
}

export function updateVoiceActivity(
  state,
  {
    rms,
    now,
    threshold = VOICE_RMS_THRESHOLD,
    silenceMs = AVATAR_SILENCE_MS,
  },
) {
  if (rms >= threshold) {
    return {
      speechStarted: true,
      lastVoiceAt: now,
      shouldStop: false,
    }
  }
  const speechStarted = Boolean(state?.speechStarted)
  const lastVoiceAt = Number(state?.lastVoiceAt) || 0
  return {
    speechStarted,
    lastVoiceAt,
    shouldStop:
      speechStarted && lastVoiceAt > 0 && now - lastVoiceAt >= silenceMs,
  }
}
