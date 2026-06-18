import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { api, setCurrentBuilding } from '../api/client'

const STORAGE_KEY = 'allgud.building'

const BuildingContext = createContext(null)

export function BuildingProvider({ children }) {
  const [buildings, setBuildings] = useState([])
  const [building, setBuildingState] = useState(localStorage.getItem(STORAGE_KEY) || '')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setCurrentBuilding(building)
  }, [building])

  const load = useCallback((preferId) => {
    setLoading(true)
    return api
      .seeds()
      .then((res) => {
        const list = res.seeds || []
        setBuildings(list)
        setBuildingState((prev) => {
          const want = preferId || prev
          if (want && list.some((b) => b.building_id === want)) return want
          return list[0]?.building_id || ''
        })
        setError(null)
        setLoading(false)
        return list
      })
      .catch((err) => {
        setError(err)
        setLoading(false)
        return []
      })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const selectBuilding = useCallback((id) => {
    localStorage.setItem(STORAGE_KEY, id)
    setBuildingState(id)
  }, [])

  const current = buildings.find((b) => b.building_id === building)

  return (
    <BuildingContext.Provider
      value={{ building, buildings, current, selectBuilding, loading, error, reload: load }}
    >
      {children}
    </BuildingContext.Provider>
  )
}

export function useBuilding() {
  const ctx = useContext(BuildingContext)
  if (!ctx) throw new Error('useBuilding must be used within BuildingProvider')
  return ctx
}
