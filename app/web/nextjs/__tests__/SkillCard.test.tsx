import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SkillCard } from '@/components/skills/SkillCard';
import { Skill } from '@/types/skill';

const mockSkill: Skill = {
  id: '1',
  name: 'Test Skill',
  description: 'A test skill for unit testing',
  version: '1.0.0',
  author: 'Test Author',
  category: 'Development',
  tags: ['javascript', 'testing'],
  tools: ['lsp_hover', 'bash'],
  hooks: ['auto-format'],
  dependencies: [],
  is_active: false,
  created_at: '2024-01-15T10:00:00Z',
  updated_at: '2024-01-15T10:00:00Z',
};

describe('SkillCard', () => {
  const mockOnActivate = jest.fn();

  beforeEach(() => {
    mockOnActivate.mockClear();
  });

  it('renders skill information correctly', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} />);
    
    expect(screen.getByText(mockSkill.name)).toBeInTheDocument();
    expect(screen.getByText(mockSkill.description)).toBeInTheDocument();
    expect(screen.getByText(mockSkill.category)).toBeInTheDocument();
    expect(screen.getByText('v1.0.0')).toBeInTheDocument();
    expect(screen.getByText('by Test Author')).toBeInTheDocument();
  });

  it('shows activate button for inactive skill', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} />);
    
    const button = screen.getByText('Активировать');
    expect(button).toBeInTheDocument();
    expect(button).toHaveClass('bg-green-100');
    expect(button).toHaveClass('text-green-700');
  });

  it('shows deactivate button for active skill', () => {
    const activeSkill = { ...mockSkill, is_active: true };
    render(<SkillCard skill={activeSkill} onActivate={mockOnActivate} />);
    
    const button = screen.getByText('Деактивировать');
    expect(button).toBeInTheDocument();
    expect(button).toHaveClass('bg-red-100');
    expect(button).toHaveClass('text-red-700');
  });

  it('calls onActivate when activation button is clicked', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} />);
    
    const button = screen.getByText('Активировать');
    fireEvent.click(button);
    
    expect(mockOnActivate).toHaveBeenCalledWith(mockSkill.name);
  });

  it('disables button when isActivating is true', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} isActivating={true} />);
    
    const button = screen.getByText('Обработка...');
    expect(button).toBeDisabled();
    expect(button).toHaveClass('opacity-50');
  });

  it('shows tags correctly', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} />);
    
    expect(screen.getByText('javascript')).toBeInTheDocument();
    expect(screen.getByText('testing')).toBeInTheDocument();
  });

  it('shows tools count correctly', () => {
    render(<SkillCard skill={mockSkill} onActivate={mockOnActivate} />);
    
    expect(screen.getByText('2 tools')).toBeInTheDocument();
  });
});