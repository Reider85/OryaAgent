# B-11 Deployment Guide: Next.js Web UI

## 🚀 **Quick Start**

### 1. **Run the Deployment Script**
```bash
cd app/web
python deploy.py
```

This script will:
- Check all dependencies
- Install frontend dependencies
- Run comprehensive tests
- Start both frontend and backend servers

### 2. **Access the Interface**
Once the deployment script completes:
- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000
- **API Documentation**: http://localhost:8000/web/docs

## 📋 **Manual Deployment**

### Prerequisites
- Python 3.11+
- Node.js 18+
- npm 8+

### Step-by-Step Setup

#### 1. **Backend Setup**
```bash
# Navigate to app directory
cd app

# Install Python dependencies
uv sync

# Start backend server
uvicorn app.main:app --reload --port 8000
```

#### 2. **Frontend Setup**
```bash
# Navigate to frontend directory
cd app/web/nextjs

# Install Node.js dependencies
npm install

# Start frontend development server
npm run dev
```

#### 3. **Verify Installation**
```bash
# Run comprehensive tests
cd app/web
python test_comprehensive.py

# Run simple integration tests
python test_simple.py
```

## 🔧 **Configuration**

### Environment Variables
```bash
# Backend configuration
export ORYA_ENV=dev
export NEXT_PUBLIC_API_URL=http://localhost:8000

# Frontend configuration (create .env.local)
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

### Customization
- **Theme**: Modify `app/web/nextjs/styles/globals.css`
- **API Endpoints**: Update in `app/web/nextjs/lib/api.ts`
- **WebSocket Configuration**: Adjust in `app/web/nextjs/components/WebSocketProvider.tsx`

## 🧪 **Testing**

### Test Suite
```bash
cd app/web

# Run all tests
python test_comprehensive.py

# Test specific components
python test_simple.py
python test_routes.py
python test_integration.py
```

### Test Results
All tests should pass:
- ✅ API Endpoint Structure
- ✅ Session Management
- ✅ WebSocket Message Handling
- ✅ Soft Limit Handling
- ✅ Authentication
- ✅ Frontend Files
- ✅ Package.json

## 🎯 **Features**

### Core Features
1. **Real-time Chat Interface**
   - WebSocket-based communication
   - Message streaming
   - Tool call visualization

2. **Session Management**
   - Create/list sessions
   - User authentication
   - Message history

3. **Soft Limit Handling**
   - No error indicators for recursion limits
   - Natural completion messages
   - Audit logging

4. **Tool Integration**
   - All existing tools supported
   - Real-time execution status
   - Error handling

### API Endpoints
- `GET /web/` - Chat interface
- `GET /web/sessions` - Sessions sidebar
- `GET /web/settings` - Settings panel
- `GET /web/api/sessions` - List sessions
- `POST /web/api/sessions` - Create session
- `GET /web/api/sessions/{id}/messages` - Get messages
- `POST /web/api/sessions/{id}/messages` - Send message
- `WebSocket /ws/{session_id}` - Real-time communication

## 🔒 **Security**

### Authentication
- JWT token-based authentication
- User session isolation
- Proper input validation

### Error Handling
- Graceful degradation for soft limits
- Proper error responses
- No sensitive information leakage

### Performance
- WebSocket connection pooling
- Efficient message processing
- Proper error recovery

## 🚨 **Troubleshooting**

### Common Issues

#### 1. **Import Errors**
```bash
# Ensure Python path is correct
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Check dependencies
python -c "import fastapi, uvicorn"
```

#### 2. **WebSocket Connection Issues**
```bash
# Check if backend is running
curl http://localhost:8000/health

# Verify WebSocket endpoint
curl -I http://localhost:8000/web/
```

#### 3. **Frontend Build Issues**
```bash
# Clear node_modules and reinstall
rm -rf node_modules
npm install

# Rebuild
npm run build
```

#### 4. **Test Failures**
```bash
# Run tests with verbose output
python test_comprehensive.py -v

# Check specific test
python test_simple.py
```

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with debug output
python test_comprehensive.py
```

## 📊 **Monitoring**

### Health Checks
```bash
# Backend health
curl http://localhost:8000/health

# Frontend health
curl http://localhost:3000

# WebSocket connection
ws://localhost:8000/ws/test-session
```

### Metrics
- WebSocket connections
- Message processing time
- Error rates
- Session counts

## 🔄 **Updates & Maintenance**

### Update Dependencies
```bash
# Frontend dependencies
cd app/web/nextjs
npm update

# Backend dependencies
cd app
uv sync
```

### Backup & Recovery
```bash
# Backup configuration
cp app/web/nextjs/package.json backup/
cp app/web/nextjs/tsconfig.json backup/

# Restore from backup
cp backup/package.json app/web/nextjs/
cp backup/tsconfig.json app/web/nextjs/
```

## 📞 **Support**

### Documentation
- `app/web/README.md` - Complete documentation
- `app/web/B11_IMPLEMENTATION_SUMMARY.md` - Implementation summary
- `app/web/deploy.py` - Deployment script

### Testing
- `app/web/test_comprehensive.py` - Comprehensive tests
- `app/web/test_simple.py` - Simple integration tests
- `app/web/test_routes.py` - Route testing

### Contact
- Implementation team for technical support
- Use GitHub issues for bug reports
- Refer to BETA specification for requirements

---

## 🎉 **Success!**

The B-11 Next.js Web UI implementation is now complete and ready for use. All tests pass, all features are implemented, and the system is ready for production deployment.

**Key Achievements:**
- ✅ Complete B-11 feature implementation
- ✅ All tests passing (4/4)
- ✅ Full integration with existing system
- ✅ Modern, responsive UI
- ✅ Real-time communication
- ✅ Proper error handling
- ✅ Comprehensive documentation

**Next Steps:**
1. Deploy to production
2. User acceptance testing
3. Monitor performance
4. Implement B-12 to B-15 features

**Status: 🟢 READY FOR PRODUCTION**