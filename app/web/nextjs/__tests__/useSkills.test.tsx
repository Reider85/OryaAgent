import { renderHook, act } from '@testing-library/react';
import { useSkills } from '@/hooks/useSkills';
import { getSkills, activateSkill } from '@/lib/api/skills';

// Mock the API functions
jest.mock('@/lib/api/skills');

const mockGetSkills = getSkills as jest.MockedFunction<typeof getSkills>;
const mockActivateSkill = activateSkill as jest.MockedFunction<typeof activateSkill>;

describe('useSkills hook', () => {
  const mockSkills = [
    {
      id: '1',
      name: 'Test Skill 1',
      description: 'Test description 1',
      version: '1.0.0',
      author: 'Test Author 1',
      category: 'Development',
      tags: ['javascript'],
      tools: ['tool1'],
      hooks: ['hook1'],
      dependencies: [],
      is_active: false,
      created_at: '2024-01-15T10:00:00Z',
      updated_at: '2024-01-15T10:00:00Z',
    },
    {
      id: '2',
      name: 'Test Skill 2',
      description: 'Test description 2',
      version: '1.0.0',
      author: 'Test Author 2',
      category: 'Testing',
      tags: ['testing'],
      tools: ['tool2'],
      hooks: ['hook2'],
      dependencies: [],
      is_active: true,
      created_at: '2024-01-15T10:00:00Z',
      updated_at: '2024-01-15T10:00:00Z',
    },
  ];

  beforeEach(() => {
    mockGetSkills.mockResolvedValue(mockSkills);
    mockActivateSkill.mockResolvedValue({
      success: true,
      is_active: true,
      message: 'Skill activated successfully',
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('fetches skills on initial render', async () => {
    const { result } = renderHook(() => useSkills());
    
    expect(result.current.loading).toBe(true);
    expect(result.current.skills).toEqual([]);
    
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    
    expect(result.current.loading).toBe(false);
    expect(result.current.skills).toEqual(mockSkills);
  });

  it('calls fetchSkills with correct parameters', async () => {
    const { result } = renderHook(() => useSkills());
    
    await act(async () => {
      await result.current.fetchSkills({ search: 'test', category: 'Development' });
    });
    
    expect(mockGetSkills).toHaveBeenCalledWith({ search: 'test', category: 'Development', tags: [] });
  });

  it('handles API errors gracefully', async () => {
    mockGetSkills.mockRejectedValue(new Error('API Error'));
    
    const { result } = renderHook(() => useSkills());
    
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    
    expect(result.current.error).toBe('Failed to fetch skills');
    expect(result.current.skills).toEqual([]);
  });

  it('toggles skill activation correctly', async () => {
    const { result } = renderHook(() => useSkills());
    
    // Wait for initial fetch
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    
    // Toggle activation
    await act(async () => {
      await result.current.toggleSkillActivation('Test Skill 1');
    });
    
    expect(mockActivateSkill).toHaveBeenCalledWith('Test Skill 1');
    expect(result.current.skills[0].is_active).toBe(true);
  });

  it('handles activation errors gracefully', async () => {
    mockActivateSkill.mockRejectedValue(new Error('Activation Error'));
    
    const { result } = renderHook(() => useSkills());
    
    // Wait for initial fetch
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    
    // Try to toggle activation
    await act(async () => {
      await expect(result.current.toggleSkillActivation('Test Skill 1')).rejects.toThrow('Failed to toggle skill activation');
    });
    
    expect(result.current.error).toBe('Failed to toggle skill activation');
  });
});