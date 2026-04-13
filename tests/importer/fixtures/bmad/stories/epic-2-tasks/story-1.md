---
title: Create Task
---
Given an authenticated user,
When they POST to /api/tasks with a title,
Then the system creates a task and returns 201 with task_id.
When the title is missing,
Then the system returns 422 with field-level validation error.
