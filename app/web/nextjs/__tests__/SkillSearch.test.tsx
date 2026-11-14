import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SkillSearch } from '@/components/skills/SkillSearch';
import { act } from 'react';

const mockOnSearch = jest.fn();
const mockOnFilter = jest.fn();

describe('SkillSearch', () => {
  beforeEach(() => {
    mockOnSearch.mockClear();
    mockOnFilter.mockClear();
  });

  it('renders search input and filters', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    expect(screen.getByPlaceholderText('Поиск навыков по названию или описанию...')).toBeInTheDocument();
    expect(screen.getByText('Категория')).toBeInTheDocument();
    expect(screen.getByText('Теги')).toBeInTheDocument();
  });

  it('calls onSearch when search button is clicked', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const searchInput = screen.getByPlaceholderText('Поиск навыков по названию или описанию...');
    const searchButton = screen.getByText('Поиск');
    
    fireEvent.change(searchInput, { target: { value: 'test query' } });
    fireEvent.click(searchButton);
    
    expect(mockOnSearch).toHaveBeenCalledWith('test query');
  });

  it('calls onSearch when Enter key is pressed in search input', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const searchInput = screen.getByPlaceholderText('Поиск навыков по названию или описанию...');
    
    fireEvent.change(searchInput, { target: { value: 'test query' } });
    fireEvent.keyPress(searchInput, { key: 'Enter', code: 'Enter' });
    
    expect(mockOnSearch).toHaveBeenCalledWith('test query');
  });

  it('calls onFilter when category is selected', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const categorySelect = screen.getByLabelText('Категория');
    
    fireEvent.change(categorySelect, { target: { value: 'Development' } });
    
    expect(mockOnFilter).toHaveBeenCalledWith({ category: 'Development', tags: [] });
  });

  it('calls onFilter when tag is toggled', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const tagButton = screen.getByText('javascript');
    
    fireEvent.click(tagButton);
    
    expect(mockOnFilter).toHaveBeenCalledWith({ category: '', tags: ['javascript'] });
    
    // Click again to untoggle
    fireEvent.click(tagButton);
    
    expect(mockOnFilter).toHaveBeenCalledWith({ category: '', tags: [] });
  });

  it('shows active filters when applied', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const categorySelect = screen.getByLabelText('Категория');
    const tagButton = screen.getByText('javascript');
    
    fireEvent.change(categorySelect, { target: { value: 'Development' } });
    fireEvent.click(tagButton);
    
    expect(screen.getByText('Активные фильтры:')).toBeInTheDocument();
    expect(screen.getByText('Development')).toBeInTheDocument();
    expect(screen.getByText('javascript')).toBeInTheDocument();
  });

  it('calls clearFilters when clear button is clicked', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const categorySelect = screen.getByLabelText('Категория');
    const tagButton = screen.getByText('javascript');
    const clearButton = screen.getByText('Очистить');
    
    fireEvent.change(categorySelect, { target: { value: 'Development' } });
    fireEvent.click(tagButton);
    fireEvent.click(clearButton);
    
    expect(mockOnSearch).toHaveBeenCalledWith('');
    expect(mockOnFilter).toHaveBeenCalledWith({});
  });

  it('shows all available categories in select', () => {
    render(<SkillSearch onSearch={mockOnSearch} onFilter={mockOnFilter} />);
    
    const categorySelect = screen.getByLabelText('Категория');
    const options = screen.getAllByRole('option');
    
    expect(options).toHaveLength(9); // 8 categories + "Все категории"
    expect(options[0]).toHaveValue('');
    expect(options[1]).toHaveValue('Development');
    expect(options[2]).toHaveValue('Code Review');
  });
});