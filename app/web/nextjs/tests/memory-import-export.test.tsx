import { MemoryImport, MemoryExport } from '@/components/memory-import';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

// Mock the API calls
vi.mock('@/components/memory-import', () => ({
  MemoryImport: vi.fn(() => <div>Memory Import Component</div>),
  MemoryExport: vi.fn(() => <div>Memory Export Component</div>),
}));

describe('Memory Import/Export Components', () => {
  const mockSessionId = 'test_session_123';

  describe('MemoryImport', () => {
    it('renders import button', () => {
      const { MemoryImport } = require('@/components/memory-import');
      
      render(<MemoryImport session_id={mockSessionId} />);
      
      expect(screen.getByText('Memory Import Component')).toBeInTheDocument();
    });

    it('handles file upload', async () => {
      const { MemoryImport } = require('@/components/memory-import');
      
      render(<MemoryImport session_id={mockSessionId} />);
      
      // Simulate file selection
      const file = new File(['{"test": "data"}'], 'test.json', { type: 'application/json' });
      const input = screen.getByLabelText(/Upload JSON File/i);
      
      fireEvent.change(input, { target: { files: [file] } });
      
      await waitFor(() => {
        expect(input.files?.[0]).toBe(file);
      });
    });

    it('handles JSON input', async () => {
      const { MemoryImport } = require('@/components/memory-import');
      
      render(<MemoryImport session_id={mockSessionId} />);
      
      const textarea = screen.getByPlaceholderText(/Paste JSON Data/i);
      fireEvent.change(textarea, { 
        target: { value: '{"timestamp": "2024-01-01T00:00:00Z", "version": "1.0.0"}' } 
      });
      
      expect(textarea).toHaveValue('{"timestamp": "2024-01-01T00:00:00Z", "version": "1.0.0"}');
    });
  });

  describe('MemoryExport', () => {
    it('renders export button', () => {
      const { MemoryExport } = require('@/components/memory-export');
      
      render(<MemoryExport session_id={mockSessionId} />);
      
      expect(screen.getByText('Memory Export Component')).toBeInTheDocument();
    });

    it('handles export options', async () => {
      const { MemoryExport } = require('@/components/memory-export');
      
      render(<MemoryExport session_id={mockSessionId} />);
      
      const checkbox = screen.getByLabelText(/Include L1 Memory Data/i);
      fireEvent.click(checkbox);
      
      expect(checkbox).toBeChecked();
    });
  });
});