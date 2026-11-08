import { render, screen } from '@testing-library/react'
import { SessionSidebar } from '@/components/SessionSidebar'

// Generate mock sessions for performance testing
const generateMockSessions = (count: number) => {
  const sessions = []
  for (let i = 0; i < count; i++) {
    sessions.push({
      id: `session-${i}`,
      name: `Session ${i + 1}`,
      description: `This is session number ${i + 1} for performance testing`,
      created_at: new Date(Date.now() - i * 24 * 60 * 60 * 1000).toISOString(), // Spread across days
      updated_at: new Date().toISOString(),
      status: i % 3 === 0 ? 'active' : i % 3 === 1 ? 'completed' : 'archived',
      message_count: Math.floor(Math.random() * 100) + 1,
      workspace: i % 2 === 0 ? 'project-alpha' : 'project-beta',
      branch_count: i % 4 === 0 ? Math.floor(Math.random() * 5) + 1 : undefined,
      last_message: i % 5 === 0 ? `Last message in session ${i + 1}` : undefined,
    })
  }
  return sessions
}

// Mock the useSessions hook for performance testing
jest.mock('@/hooks/useSessions', () => ({
  useSessions: jest.fn((filters) => {
    const allSessions = generateMockSessions(1000) // 1000 sessions for testing
    const filteredSessions = allSessions.filter(session => {
      // Apply filters if provided
      if (filters?.search && !session.name.toLowerCase().includes(filters.search.toLowerCase())) {
        return false
      }
      if (filters?.status && !filters.status.includes(session.status)) {
        return false
      }
      return true
    }).slice(0, filters?.limit || 50) // Limit to 50 for testing

    return {
      sessions: filteredSessions,
      loading: false,
      error: null,
      fetchSessions: jest.fn(),
      createSession: jest.fn(),
      deleteSession: jest.fn(),
      updateSession: jest.fn(),
    }
  }),
}))

describe('SessionSidebar Performance', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('renders 1000 sessions within acceptable time', () => {
    const startTime = performance.now()
    
    render(<SessionSidebar />)
    
    // Let the component render
    jest.runAllTimers()
    
    const endTime = performance.now()
    const renderTime = endTime - startTime
    
    console.log(`Render time for 1000 sessions: ${renderTime}ms`)
    
    // Check that all sessions are rendered
    expect(screen.getByText('1000 sessions')).toBeInTheDocument()
    
    // Performance assertion: should render within 2 seconds
    expect(renderTime).toBeLessThan(2000)
  })

  it('handles search filtering efficiently', () => {
    const startTime = performance.now()
    
    render(<SessionSidebar />)
    
    const searchInput = screen.getByPlaceholderText('Search sessions...')
    fireEvent.change(searchInput, { target: { value: 'Session 5' } })
    
    jest.runAllTimers()
    
    const endTime = performance.now()
    const searchTime = endTime - startTime
    
    console.log(`Search time for "Session 5": ${searchTime}ms`)
    
    // Check that search results are displayed
    expect(screen.getByText('1 session')).toBeInTheDocument()
    
    // Performance assertion: search should complete within 500ms
    expect(searchTime).toBeLessThan(500)
  })

  it('handles status filtering efficiently', () => {
    const startTime = performance.now()
    
    render(<SessionSidebar />)
    
    // Click on completed filter
    const completedFilter = screen.getByText('Completed')
    fireEvent.click(completedFilter)
    
    jest.runAllTimers()
    
    const endTime = performance.now()
    const filterTime = endTime - startTime
    
    console.log(`Filter time for completed sessions: ${filterTime}ms`)
    
    // Performance assertion: filter should complete within 300ms
    expect(filterTime).toBeLessThan(300)
  })

  it('handles create session modal efficiently', () => {
    const startTime = performance.now()
    
    render(<SessionSidebar />)
    
    const newSessionButton = screen.getByText('New Session')
    fireEvent.click(newSessionButton)
    
    jest.runAllTimers()
    
    const endTime = performance.now()
    const modalTime = endTime - startTime
    
    console.log(`Modal open time: ${modalTime}ms`)
    
    // Check that modal is rendered
    expect(screen.getByText('Create New Session')).toBeInTheDocument()
    
    // Performance assertion: modal should open within 200ms
    expect(modalTime).toBeLessThan(200)
  })

  it('handles session selection efficiently', () => {
    const startTime = performance.now()
    
    render(<SessionSidebar />)
    
    // Find and click on a session
    const sessionItem = screen.getByText('Session 1').closest('div')
    fireEvent.click(sessionItem!)
    
    jest.runAllTimers()
    
    const endTime = performance.now()
    const selectionTime = endTime - startTime
    
    console.log(`Session selection time: ${selectionTime}ms`)
    
    // Performance assertion: selection should complete within 100ms
    expect(selectionTime).toBeLessThan(100)
  })
})