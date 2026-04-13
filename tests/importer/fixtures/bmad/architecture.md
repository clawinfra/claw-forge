# Architecture

## Tech Stack
- Backend: Python 3.12 with FastAPI
- Frontend: React 18 + TypeScript + Vite
- Database: PostgreSQL 15
- Auth: JWT with refresh tokens

## Database Schema
users table: id UUID PK, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR NOT NULL, created_at TIMESTAMP
tasks table: id UUID PK, owner_id UUID FK users.id, title VARCHAR(200) NOT NULL, status VARCHAR(20) DEFAULT 'todo', created_at TIMESTAMP

## API Endpoints
POST /api/auth/register - Register new user
POST /api/auth/login    - Login and receive tokens
GET  /api/tasks         - List user's tasks
POST /api/tasks         - Create a task
