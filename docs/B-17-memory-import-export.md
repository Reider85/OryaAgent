# B-17: Memory UI Import/Export Implementation

## Overview

B-17 implements JSON import/export functionality for the memory management UI in Next.js. This allows users to backup their memory data, share it between sessions, or migrate memories across different environments.

## Features

### Import Functionality
- **File Upload**: Drag-and-drop or click to upload JSON files
- **JSON Input**: Paste JSON data directly into a text area
- **Validation**: Real-time validation before import
- **Merge Modes**:
  - Overwrite: Replace all existing data
  - Merge: Add to existing data
  - Skip Existing: Skip files that already exist
- **Error Handling**: Clear error messages and warnings

### Export Functionality
- **Export Options**: Choose to include/exclude L1 memory data (SQLite entries)
- **Preview**: See what data will be exported before downloading
- **Download**: One-click download of JSON file
- **Summary**: Display export statistics (file counts, entry counts)

## Implementation Details

### Backend Integration
The Next.js UI integrates with the existing Python backend API endpoints:

- `GET /api/memory/export` - Export memory data
- `POST /api/memory/import` - Import memory data from JSON
- `POST /api/memory/import-upload` - File upload import
- `POST /api/memory/validate` - Validate import data

### Data Structure

```json
{
  "timestamp": "2026-10-20T12:00:00Z",
  "version": "1.0.0",
  "l0_files": {
    "PROJECT.md": "# Project Context\n...",
    "LEARNED.md": "- Learned fact 1\n...",
    "PREFERENCES.md": "{\"style\": \"detailed\"}",
    "FACTS.md": "- Fact 1: Project uses Next.js\n...",
    "DECISIONS.md": "- Decision 1: Use TypeScript\n...",
    "MEMORY_INDEX.md": "# Memory Index\n..."
  },
  "l1_files": [
    {
      "name": "learned_facts",
      "entries": [
        {
          "id": "memory_1234567890",
          "session_id": "session_1234567890",
          "content": "This is a test memory entry",
          "metadata": { "source": "user", "type": "fact" },
          "created_at": "2024-01-15T10:00:00Z",
          "updated_at": "2024-01-15T10:00:00Z"
        }
      ],
      "metadata": {
        "size": 1024,
        "last_modified": "2024-01-15T10:00:00Z"
      }
    }
  ]
}
```

### Components

#### MemoryImport Component
- **Location**: `app/web/nextjs/components/memory-import.tsx`
- **Props**: 
  - `session_id`: Current session ID
  - `onImportComplete`: Callback when import completes
- **Features**:
  - File upload with drag-and-drop
  - JSON text input
  - Import mode selection
  - Real-time validation
  - Error handling and feedback

#### MemoryExport Component
- **Location**: `app/web/nextjs/components/memory-export.tsx`
- **Props**:
  - `session_id`: Current session ID
  - `onExportComplete`: Callback when export completes
- **Features**:
  - Export options (L0/L1 data)
  - Export summary
  - JSON preview
  - Download functionality

### API Routes

#### Export API
- **Route**: `app/web/nextjs/app/api/memory/export/route.ts`
- **Method**: GET
- **Query Params**:
  - `session_id`: Required
  - `include_l1`: Optional (default: true)
- **Response**: JSON export data

#### Import API
- **Route**: `app/web/nextjs/app/api/memory/import/route.ts`
- **Method**: POST
- **Body**:
  ```json
  {
    "session_id": "string",
    "source_file": "string (JSON data)",
    "merge_mode": "overwrite|merge|skip_existing",
    "validate_only": false
  }
  ```

#### File Upload API
- **Route**: `app/web/nextjs/app/api/memory/import-upload/route.ts`
- **Method**: POST
- **Form Data**:
  - `file`: JSON file
  - `session_id`: Session ID
  - `merge_mode`: Import mode

#### Validation API
- **Route**: `app/web/nextjs/app/api/memory/validate/route.ts`
- **Method**: POST
- **Body**:
  ```json
  {
    "source_file": "string (JSON data)"
  }
  ```

## Usage

### Import Memory Data
1. Click the "Import Memory" button in the memory management page
2. Choose between file upload or JSON paste
3. Select import mode (overwrite/merge/skip_existing)
4. Validate the data (optional but recommended)
5. Click "Import Data" to complete the import

### Export Memory Data
1. Click the "Export Memory" button in the memory management page
2. Choose whether to include L1 data (SQLite entries)
3. Click "Generate Export" to create the export
4. Review the export summary and preview
5. Click "Download JSON File" to save the data

## Error Handling

### Common Errors
- **Invalid JSON**: Clear error message with validation details
- **File Size Limits**: Warning when files exceed maximum size
- **Session ID Missing**: Clear error message
- **Network Errors**: Retry mechanism with user feedback

### Validation Warnings
- Empty content entries
- Missing metadata
- File size approaching limits
- Duplicate data warnings

## Testing

### Unit Tests
- Import component file upload functionality
- Export component download functionality
- API route integration
- Error handling scenarios

### Integration Tests
- End-to-end import/export workflow
- Data validation and integrity checks
- UI/UX testing with user feedback

### Mock Data
- Mock API responses for development
- Sample export data for testing
- Error scenarios for validation

## Security Considerations

- Input validation for all JSON data
- File type restrictions (JSON only)
- Session-based access control
- Error message sanitization
- File size limits

## Performance Considerations

- Lazy loading of large export data
- Optimistic UI updates
- Debounced validation
- Efficient file handling

## Future Enhancements

- Compression for large export files
- Import/export scheduling
- Version comparison tools
- Data migration wizards
- Cloud storage integration

## Dependencies

- React 18
- Next.js 14
- TypeScript
- Tailwind CSS
- Lucide React icons
- shadcn/ui components

## File Structure

```
app/web/nextjs/
├── app/
│   ├── api/
│   │   ├── memory/
│   │   │   ├── export/
│   │   │   │   └── route.ts
│   │   │   ├── import/
│   │   │   │   └── route.ts
│   │   │   ├── import-upload/
│   │   │   │   └── route.ts
│   │   │   └── validate/
│   │   │       └── route.ts
│   └── memory/
│       └── page.tsx (updated with import/export buttons)
├── components/
│   ├── ui/ (existing components)
│   ├── memory-import.tsx (new)
│   └── memory-export.tsx (new)
└── tests/
    └── memory-import-export.test.tsx (new)
```

## Implementation Status

✅ **Completed**:
- Backend API routes for import/export
- MemoryImport component with file upload and JSON input
- MemoryExport component with preview and download
- Integration with existing memory management page
- Error handling and validation
- Documentation

🔄 **In Progress**:
- Comprehensive testing
- Performance optimization
- User experience refinements

📋 **Planned**:
- Additional validation rules
- Export file compression
- Cloud storage integration

## Acceptance Criteria

✅ Import functionality:
- File upload (drag & drop + browse)
- JSON string paste option
- Three merge modes (overwrite/merge/skip_existing)
- Real-time validation with error display
- Import progress feedback

✅ Export functionality:
- Export L0 + optional L1 data
- Download as JSON file
- Export summary preview

✅ UI Integration:
- Integrated with existing memory sidebar (B-16)
- Consistent with Next.js design system
- Proper error handling and user feedback

✅ Data Integrity:
- Validation prevents invalid imports
- Proper error handling for corrupt data
- Size limits enforced per file type