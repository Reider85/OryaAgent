/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SessionSidebar } from '@/components/SessionSidebar'
import { SessionInfo } from '@/types/session'

// Mock the useSessions hook
jest.mock('@/hooks/useSessions', () => ({
  useSessions: jest.fn(() => ({
    sessions: [
      {
        id: '1',
        name: 'Test Session 1',
        description: 'First test session',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status: 'active' as const,
        message_count: 5,
        workspace: 'test-project',
      },
      {
        id: '2',
        name: 'Test Session 2',
        description: 'Second test session',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status: 'completed' as const,
        message_count: 10,
      },
    ],
    loading: false,
    error: null,
    fetchSessions: jest.fn(),
    createSession: jest.fn(),
    deleteSession: jest.fn(),
    updateSession: jest.fn(),
  })),
}))

describe('SessionSidebar', () => {
  it('renders session list with correct number of sessions', () => {
    render(<SessionSidebar />)
    
    expect(screen.getByText('Sessions')).toBeInTheDocument()
    expect(screen.getByText('2 sessions')).toBeInTheDocument()
    
    // Check for session names
    expect(screen.getByText('Test Session 1')).toBeInTheDocument()
    expect(screen.getByText('Test Session 2')).toBeInTheDocument()
  })

  it('shows loading state when loading', () => {
    // Mock loading state
    jest.mocked(require('@/hooks/useSessions').useSessions).mockReturnValue({
      sessions: [],
      loading: true,
      error: null,
      fetchSessions: jest.fn(),
      createSession: jest.fn(),
      deleteSession: jest.fn(),
      updateSession: jest.fn(),
    })

    render(<SessionSidebar />)
    
    expect(screen.getByText('Loading sessions...')).toBeInTheDocument()
  })

  it('shows error state when there is an error', () => {
    // Mock error state
    jest.mocked(require('@/hooks/useSessions').useSessions).mockReturnValue({
      sessions: [],
      loading: false,
      error: 'Failed to load sessions',
      fetchSessions: jest.fn(),
      createSession: jest.fn(),
      deleteSession: jest.fn(),
      updateSession: jest.fn(),
    })

    render(<SessionSidebar />)
    
    expect(screen.getByText('Error')).toBeInTheDocument()
    expect(screen.getByText('Failed to load sessions')).toBeInTheDocument()
  })

  it('handles session selection', () => {
    render(<SessionSidebar />)
    
    const sessionItem = screen.getByText('Test Session 1').closest('div')
    expect(sessionItem).toBeInTheDocument()
    
    // The session should be selected by default
    expect(sessionItem).toHaveClass('bg-blue-50')
    expect(sessionItem).toHaveClass('border-blue-200')
  })

  it('handles search input', () => {
    render(<SessionSidebar />)
    
    const searchInput = screen.getByPlaceholderText('Search sessions...')
    expect(searchInput).toBeInTheDocument()
    
    fireEvent.change(searchInput, { target: { value: 'Test' } })
    expect(searchInput).toHaveValue('Test')
  })

  it('handles status filter', () => {
    render(<SessionSidebar />)
    
    // Check for filter buttons
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Archived')).toBeInTheDocument()
    
    // Click on completed filter
    const completedFilter = screen.getByText('Completed')
    fireEvent.click(completedFilter)
    
    // The button should be selected
    expect(completedFilter).toHaveClass('bg-blue-100')
    expect(completedFilter).toHaveClass('text-blue-800')
  })

  it('shows create session modal', () => {
    render(<SessionSidebar />)
    
    const newSessionButton = screen.getByText('New Session')
    expect(newSessionButton).toBeInTheDocument()
    
    fireEvent.click(newSessionButton)
    
    expect(screen.getByText('Create New Session')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Enter session name')).toBeInTheDocument()
  })
})