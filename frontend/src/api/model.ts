import { useSyncExternalStore } from 'react'

// The AI model picked in the header, per browser. Sent as X-LLM-Model on AI
// requests; the server only accepts models on its allowlist and otherwise
// uses its default.

const KEY = 'voltride.llmModel'
let memoryModel: string | null = null
const listeners = new Set<() => void>()

export function selectedModel(): string | null {
  try {
    return localStorage.getItem(KEY) ?? memoryModel
  } catch {
    return memoryModel
  }
}

export function selectModel(model: string): void {
  memoryModel = model
  try {
    localStorage.setItem(KEY, model)
  } catch {
    // storage unavailable: keep it for this session only
  }
  listeners.forEach((l) => l())
}

export function useSelectedModel(): string | null {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange)
      return () => listeners.delete(onChange)
    },
    selectedModel,
    selectedModel,
  )
}
