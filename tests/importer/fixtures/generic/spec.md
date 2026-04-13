# TaskTracker

A task management app for small teams.

## Tech Stack
Python FastAPI backend, React TypeScript frontend, PostgreSQL database.

## Authentication

### User Registration
Users provide email and password to create an account.
- System validates email format
- System rejects duplicate emails with error
- System hashes password before storing

### User Login
Users submit credentials to receive access tokens.
- System returns JWT on valid credentials
- System returns 401 on invalid credentials

## Task Management

### Create Task
Authenticated users create tasks with a title.
- System validates title is not empty
- System returns created task with id
