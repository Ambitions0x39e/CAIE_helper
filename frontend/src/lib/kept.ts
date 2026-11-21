import { useEffect, useState } from 'react'

/** Values that outlive the component holding them, for as long as the app is
 * open. `PushTrack` unmounts the view it slides away from, so plain state is
 * gone the moment the user switches tab. */
const kept = new Map<string, unknown>()

/** `useState`, remembered under `key` across unmounts. No key, no memory. */
export function useKept<T>(key: string | undefined, initial: T) {
  const state = useState<T>(() =>
    key !== undefined && kept.has(key) ? (kept.get(key) as T) : initial,
  )
  const value = state[0]
  useEffect(() => {
    if (key !== undefined) kept.set(key, value)
  }, [key, value])
  return state
}
